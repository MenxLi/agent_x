import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient

from xun.command import Command, CommandRegistry
from xun.display_web import DisplayWeb


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

    def instruct(self, content: str) -> _Execution:
        self.instructions.append(content)
        return _Execution(self.instruction_called)

    def execute(self) -> None:
        self.instruction_called.set()


class DisplayWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.agent = _Agent(self.root)
        self.display = DisplayWeb(assets_dir=self.root / "missing")
        self.display.bind_agent(self.agent)  # type: ignore[arg-type]
        self.client = TestClient(self.display.app)
        self.client.__enter__()

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

        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "message", "content": "hello"})
            websocket.send_json({"type": "command", "name": "sample", "arguments": "value"})

        self.assertTrue(self.agent.instruction_called.wait(1))
        self.assertTrue(command_called.wait(1))
        self.assertEqual(self.agent.instructions, ["hello"])
        names = [event["name"] for event in self.display._store.list()]
        self.assertIn("InfoEvent", names)
        self.assertIn("CommandEvent", names)

    def test_server_can_stop_and_restart(self) -> None:
        display = DisplayWeb(port=0, assets_dir=self.root / "missing")
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
