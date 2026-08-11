import unittest
from types import SimpleNamespace

from xun.command import CommandRegistry
from xun.display_abstract import ShowToolsEvent
from xun.toolbox import ToolBox
from xun.toolcall import tool_attr


class _CaptureDisplay:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class ToolsCommandTest(unittest.TestCase):
    def test_emits_structured_tool_metadata(self) -> None:
        @tool_attr(required_capabilities=["vision"])
        def inspect_image(path: str) -> str:
            """Inspect an image file."""
            return path

        display = _CaptureDisplay()
        agent = SimpleNamespace(display=display, toolbox=ToolBox().register(inspect_image))

        CommandRegistry().with_defaults().get("tools").invoke(agent)  # type: ignore[arg-type,union-attr]

        self.assertEqual(len(display.events), 1)
        event = display.events[0]
        self.assertIsInstance(event, ShowToolsEvent)
        assert isinstance(event, ShowToolsEvent)
        self.assertEqual(event.model_dump(), {
            "tools": [{
                "name": "inspect_image",
                "description": "Inspect an image file.",
                "required_capabilities": ["vision"],
            }],
        })

    def test_emits_empty_tool_list(self) -> None:
        display = _CaptureDisplay()
        agent = SimpleNamespace(display=display, toolbox=ToolBox())

        CommandRegistry().with_defaults().get("tools").invoke(agent)  # type: ignore[arg-type,union-attr]

        self.assertEqual(display.events, [ShowToolsEvent(tools=[])])


if __name__ == "__main__":
    unittest.main()