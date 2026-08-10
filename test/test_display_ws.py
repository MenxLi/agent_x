import asyncio
import json
import threading
import unittest

from xun.display_ws import DisplayWS


class _Execution:
    def __init__(self, called: threading.Event) -> None:
        self._called = called

    def execute(self) -> None:
        self._called.set()


class _Agent:
    def __init__(self, called: threading.Event) -> None:
        self.called = called
        self.instructions: list[str] = []

    def instruct(self, content: str) -> _Execution:
        self.instructions.append(content)
        return _Execution(self.called)


class _Socket:
    def __init__(self, message: dict) -> None:
        self._message = json.dumps(message)
        self._sent = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return self._message


class DisplayWSTest(unittest.TestCase):
    def test_message_executes_on_bound_agent(self) -> None:
        called = threading.Event()
        agent = _Agent(called)
        display = DisplayWS()
        self.addCleanup(display.stop)
        display.bind_agent(agent)  # type: ignore[arg-type]

        asyncio.run(display._handler(_Socket({
            "type": "message",
            "content": " first line\nsecond line ",
        })))

        self.assertTrue(called.wait(1))
        self.assertEqual(agent.instructions, ["first line\nsecond line"])

    def test_server_can_stop_and_restart(self) -> None:
        display = DisplayWS(port=0)
        self.addCleanup(display.stop)

        display.start()
        self.assertTrue(display._started)
        display.stop()
        self.assertFalse(display._started)

        display.start()
        self.assertTrue(display._started)


if __name__ == "__main__":
    unittest.main()
