import unittest

from xun.command import CommandRegistry
from xun.display_abstract import ShowToolsEvent
from xun.toolbox import ToolBox
from xun.toolcall import tool_attr


class _CapturingAgent:
    def __init__(self, toolbox: ToolBox) -> None:
        self.toolbox = toolbox
        self.events: list[object] = []

    def display_event(self, event: object) -> None:
        self.events.append(event)


class ToolsCommandTest(unittest.TestCase):
    def test_emits_structured_tool_metadata(self) -> None:
        @tool_attr(required_capabilities=["vision"])
        def inspect_image(path: str) -> str:
            """Inspect an image file."""
            return path

        agent = _CapturingAgent(ToolBox().register(inspect_image))

        CommandRegistry().with_defaults().get("tools").invoke(agent)  # type: ignore[arg-type]

        self.assertEqual(len(agent.events), 1)
        event = agent.events[0]
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
        agent = _CapturingAgent(ToolBox())

        CommandRegistry().with_defaults().get("tools").invoke(agent)  # type: ignore[arg-type]

        self.assertEqual(agent.events, [ShowToolsEvent(tools=[])])


if __name__ == "__main__":
    unittest.main()