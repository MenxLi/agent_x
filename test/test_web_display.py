import threading
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from xun.command import Command, CommandRegistry
from xun.display_web import WebDisplay


class _Execution:
    def __init__(self, called: threading.Event) -> None:
        self.called = called

    def execute(self) -> None:
        self.called.set()


class _Agent:
    def __init__(self, workdir: Path) -> None:
        self.identifier = "agent-1"
        self.name = "Xun"
        self.workdir = workdir
        self.command = CommandRegistry()
        self.instruction_called = threading.Event()
        self.instructions: list[str] = []
        self.images: list[list[str] | None] = []
        self.app_config = SimpleNamespace(provider=SimpleNamespace(
            openai_model="test-model",
            model_capabilities={"vision"},
        ))

    def instruct(self, content: str, images: list[str] | None = None) -> _Execution:
        self.instructions.append(content)
        self.images.append(images)
        return _Execution(self.instruction_called)

    def execute(self) -> None:
        self.instruction_called.set()


class WebDisplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.agent = _Agent(self.root)
        self.display = WebDisplay(token="test-token", assets_dir=self.root / "missing")
        self.display.bind_agent(self.agent)  # type: ignore[arg-type]
        self.client = TestClient(self.display.app)
        self.client.__enter__()
        self.client.headers["Authorization"] = "Bearer test-token"

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.display.stop()
        self.tempdir.cleanup()

    def test_lists_agents_commands_and_files(self) -> None:
        self.agent.command.register(Command("sample", "Sample command.", lambda _agent: None))
        (self.root / "folder").mkdir()
        (self.root / "note.md").write_text("# note", encoding="utf-8")

        agents = self.client.get("/api/agents").json()
        commands = self.client.get("/api/commands").json()
        listing = self.client.get("/api/files", params={"agent_id": "agent-1"}).json()

        self.assertEqual(Path(agents[0]["workdir"]), self.root.resolve())
        self.assertEqual([command["name"] for command in commands], ["help", "sample"])
        self.assertEqual([entry["name"] for entry in listing["entries"]], ["folder", "note.md"])
        self.assertTrue(listing["entries"][1]["viewable"])

    def test_upload_view_download_and_delete(self) -> None:
        response = self.client.post(
            "/api/files/upload",
            params={"agent_id": "agent-1", "path": ""},
            files=[("files", ("note.txt", b"hello web", "text/plain"))],
        )
        self.assertEqual(response.json(), {"uploaded": ["note.txt"]})

        preview = self.client.get(
            "/api/files/view",
            params={"agent_id": "agent-1", "path": "note.txt"},
        )
        self.assertEqual(preview.json()["content"], "hello web")

        download = self.client.get(
            "/api/files/download",
            params={"agent_id": "agent-1", "path": "note.txt"},
        )
        self.assertEqual(download.content, b"hello web")

        deleted = self.client.delete(
            "/api/files",
            params={"agent_id": "agent-1", "path": "note.txt"},
        )
        self.assertEqual(deleted.json(), {"deleted": True})
        self.assertFalse((self.root / "note.txt").exists())

        target = self.root / "target.txt"
        target.write_text("keep", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(target)
        self.client.delete(
            "/api/files",
            params={"agent_id": "agent-1", "path": "link.txt"},
        )
        self.assertFalse(link.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_rejects_paths_outside_workdir(self) -> None:
        response = self.client.get(
            "/api/files/view",
            params={"agent_id": "agent-1", "path": "../secret.txt"},
        )
        self.assertEqual(response.status_code, 400)

        missing = self.client.get(
            "/api/files/view",
            params={"agent_id": "agent-1", "path": "missing.txt"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_websocket_dispatches_messages_and_commands(self) -> None:
        command_called = threading.Event()
        self.agent.command.register(Command("sample", "Sample command.", lambda _agent, _args: command_called.set()))

        with self.client.websocket_connect("/ws", headers={"Authorization": "Bearer test-token"}) as websocket:
            websocket.send_json({"type": "message", "content": "hello"})
            websocket.send_json({"type": "command", "name": "sample", "arguments": "value"})

        self.assertTrue(self.agent.instruction_called.wait(1))
        self.assertTrue(command_called.wait(1))
        self.assertEqual(self.agent.instructions, ["hello"])
        names = [event["name"] for event in self.display._store.list()]
        self.assertIn("UserMessageEvent", names)
        self.assertIn("CommandEvent", names)

    def test_authentication_base_path_and_capabilities(self) -> None:
        display = WebDisplay(
            token="fixed-token",
            base_path="/agents/research/",
            assets_dir=self.root / "missing",
        )
        display.bind_agent(self.agent)  # type: ignore[arg-type]
        with TestClient(display.app) as client:
            self.assertEqual(client.get("/agents/research/api/agents").status_code, 401)
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/agents/research/ws"):
                    pass

            bearer = client.get(
                "/agents/research/api/capabilities",
                headers={"Authorization": "Bearer fixed-token"},
            )
            self.assertEqual(bearer.json(), {"model": "test-model", "capabilities": ["vision"]})

            bootstrap = client.get(
                "/agents/research/?token=fixed-token",
                follow_redirects=False,
            )
            self.assertEqual(bootstrap.status_code, 303)
            self.assertEqual(bootstrap.headers["location"], "./")
            self.assertIn("Path=/agents/research/", bootstrap.headers["set-cookie"])
            self.assertEqual(client.get("/agents/research/api/agents").status_code, 200)
            with client.websocket_connect("/agents/research/ws"):
                pass

        generated = WebDisplay(assets_dir=self.root / "missing")
        self.assertTrue(generated.token)
        self.assertIn("?token=", generated.access_url)

    def test_image_upload_persists_and_dispatches_attachment(self) -> None:
        output = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
        response = self.client.post(
            "/api/attachments",
            files=[("files", ("sample.png", output.getvalue(), "image/png"))],
        )
        self.assertEqual(response.status_code, 200)
        attachment_id = response.json()["attachments"][0]
        attachment_path = self.root / ".xun" / "attachments" / attachment_id
        self.assertTrue(attachment_path.is_file())

        with self.client.websocket_connect("/ws", headers={"Authorization": "Bearer test-token"}) as websocket:
            websocket.send_json({"type": "message", "content": "inspect", "attachments": [attachment_id]})

        self.assertTrue(self.agent.instruction_called.wait(1))
        self.assertEqual(self.agent.instructions, ["inspect"])
        self.assertEqual(self.agent.images, [[str(attachment_path.resolve())]])
        attachment = self.client.get(f"/api/attachments/{attachment_id}")
        self.assertEqual(attachment.content, output.getvalue())
        event = self.display._store.list()[-1]
        self.assertEqual(event["name"], "UserMessageEvent")
        self.assertEqual(event["event"], {"content": "inspect", "attachments": [attachment_id]})

    def test_uses_configured_attachment_directory(self) -> None:
        directory = self.root / "durable"
        display = WebDisplay(token="test-token", attachments_dir=directory, assets_dir=self.root / "missing")
        display.bind_agent(self.agent)  # type: ignore[arg-type]
        self.assertEqual(display._attachment_store().directory, directory.resolve())

    def test_server_can_stop_and_restart(self) -> None:
        display = WebDisplay(port=0, assets_dir=self.root / "missing")
        self.addCleanup(display.stop)
        display.start()
        first_port = display.port
        self.assertTrue(display._thread and display._thread.is_alive())
        display.stop()
        display.start()
        self.assertGreater(first_port, 0)
        self.assertTrue(display._thread and display._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
