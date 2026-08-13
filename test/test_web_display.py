import base64
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
from xun.conversation import Conversation
from xun.display_abstract import UserCommandEvent, UserMessageEvent
from xun.display_web import WebDisplay


class _Execution:
    def __init__(self, called: threading.Event) -> None:
        self.called = called

    def execute(self) -> None:
        self.called.set()


class _Agent:
    def __init__(self, workdir: Path, identifier: str = "agent-1", name: str = "Xun") -> None:
        self.identifier = identifier
        self.name = name
        self.workdir = workdir
        self.command = CommandRegistry()
        self.conversation = Conversation()
        self.display: WebDisplay | None = None
        self.instruction_called = threading.Event()
        self.cancel_called = threading.Event()
        self.instructions: list[str] = []
        self.images: list[list[str] | None] = []
        self.app_config = SimpleNamespace(provider=SimpleNamespace(
            openai_model="test-model",
            model_capabilities={"vision"},
        ))

    def instruct(self, content: str, images: list[str] | None = None) -> _Execution:
        self.instructions.append(content)
        self.images.append(images)
        self.conversation.add_user_message(content, images)
        assert self.display is not None
        self.display.emit(UserMessageEvent.from_inputs(content, images))
        return _Execution(self.instruction_called)

    def execute(self) -> None:
        self.instruction_called.set()

    def cancel(self) -> None:
        self.cancel_called.set()

    def execute_command(self, name: str, arguments: str | None = None) -> None:
        assert self.display is not None
        self.display.emit(UserCommandEvent(name=name, arguments=arguments))
        command = self.command.get(name)
        if command is not None:
            command.invoke(self, arguments)  # type: ignore[arg-type]


class WebDisplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.agent = _Agent(self.root)
        self.display = WebDisplay(token="test-token", assets_dir=self.root / "missing", expose_files=True)
        self.agent.display = self.display
        self.display.bind(self.agent)  # type: ignore[arg-type]
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
        commands = self.client.get("/api/commands/agent-1").json()
        listing = self.client.get("/api/files/agent-1").json()

        self.assertEqual(agents[0]["identifier"], "agent-1")
        self.assertEqual(Path(agents[0]["workdir"]), self.root.resolve())
        self.assertEqual([command["name"] for command in commands], ["help", "sample"])
        self.assertEqual([entry["name"] for entry in listing["entries"]], ["folder", "note.md"])
        self.assertTrue(listing["entries"][1]["viewable"])

    def test_file_routes_are_opt_in(self) -> None:
        display = WebDisplay(token="test-token", assets_dir=self.root / "missing")
        display.bind(self.agent)  # type: ignore[arg-type]

        with TestClient(display.app, headers={"Authorization": "Bearer test-token"}) as client:
            self.assertEqual(client.get("/api/config").json(), {"expose_files": False})
            self.assertEqual(client.get("/api/files/agent-1").status_code, 404)

        self.assertEqual(self.client.get("/api/config").json(), {"expose_files": True})

    def test_upload_view_download_and_delete(self) -> None:
        response = self.client.post(
            "/api/files/agent-1/upload",
            params={"path": ""},
            files=[("files", ("note.txt", b"hello web", "text/plain"))],
        )
        self.assertEqual(response.json(), {"uploaded": ["note.txt"]})

        preview = self.client.get(
            "/api/files/agent-1/view",
            params={"path": "note.txt"},
        )
        self.assertEqual(preview.json()["content"], "hello web")

        download = self.client.get(
            "/api/files/agent-1/download",
            params={"path": "note.txt"},
        )
        self.assertEqual(download.content, b"hello web")

        deleted = self.client.delete(
            "/api/files/agent-1",
            params={"path": "note.txt"},
        )
        self.assertEqual(deleted.json(), {"deleted": True})
        self.assertFalse((self.root / "note.txt").exists())

        target = self.root / "target.txt"
        target.write_text("keep", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(target)
        self.client.delete(
            "/api/files/agent-1",
            params={"path": "link.txt"},
        )
        self.assertFalse(link.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_rejects_paths_outside_workdir(self) -> None:
        response = self.client.get(
            "/api/files/agent-1/view",
            params={"path": "../secret.txt"},
        )
        self.assertEqual(response.status_code, 400)

        missing = self.client.get(
            "/api/files/agent-1/view",
            params={"path": "missing.txt"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_websocket_dispatches_messages_and_commands_to_selected_agent(self) -> None:
        second_root = self.root / "second"
        second_root.mkdir()
        second_agent = _Agent(second_root, "agent-2", "Research")
        second_agent.display = self.display
        self.display.bind(second_agent)  # type: ignore[arg-type]
        command_called = threading.Event()
        second_agent.command.register(Command("sample", "Sample command.", lambda _agent, _args: command_called.set()))

        with self.client.websocket_connect("/ws", headers={"Authorization": "Bearer test-token"}) as websocket:
            websocket.send_json({"type": "message", "agent_id": "agent-2", "content": "hello"})
            websocket.send_json({"type": "command", "agent_id": "agent-2", "name": "sample", "arguments": "value"})

        self.assertTrue(second_agent.instruction_called.wait(1))
        self.assertTrue(command_called.wait(1))
        self.assertEqual(second_agent.instructions, ["hello"])
        self.assertEqual(self.agent.instructions, [])
        names = [event["name"] for event in self.display._store.list()]
        self.assertIn("UserMessageEvent", names)
        self.assertIn("UserCommandEvent", names)

    def test_websocket_dispatches_cancel_immediately(self) -> None:
        self.display._running_agents.add("agent-1")
        with self.client.websocket_connect("/ws", headers={"Authorization": "Bearer test-token"}) as websocket:
            websocket.send_json({"type": "cancel", "agent_id": "agent-1"})

        self.assertTrue(self.agent.cancel_called.wait(1))

    def test_authentication_base_path_and_capabilities(self) -> None:
        display = WebDisplay(
            token="fixed-token",
            base_path="/agents/research/",
            assets_dir=self.root / "missing",
        )
        display.bind(self.agent)  # type: ignore[arg-type]
        with TestClient(display.app) as client:
            self.assertEqual(client.get("/agents/research/api/agents").status_code, 401)
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/agents/research/ws"):
                    pass

            bearer = client.get(
                "/agents/research/api/capabilities/agent-1",
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

    def test_image_message_dispatches_data_url(self) -> None:
        output = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
        image_url = f"data:image/png;base64,{base64.b64encode(output.getvalue()).decode('ascii')}"

        with self.client.websocket_connect("/ws", headers={"Authorization": "Bearer test-token"}) as websocket:
            websocket.send_json({
                "type": "message",
                "agent_id": "agent-1",
                "content": "inspect",
                "images": [{"kind": "base64", "value": image_url}],
            })

        self.assertTrue(self.agent.instruction_called.wait(1))
        self.assertEqual(self.agent.instructions, ["inspect"])
        self.assertEqual(self.agent.images, [[image_url]])
        event = self.display._store.list()[-1]
        self.assertEqual(event["name"], "UserMessageEvent")
        self.assertEqual(event["event"], {
            "content": "inspect",
            "images": [{"kind": "base64", "value": image_url}],
        })

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
