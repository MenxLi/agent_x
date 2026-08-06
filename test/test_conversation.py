import base64
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from xun.conversation import Conversation
from xun.entrypoint import MessageInstruction, input_to_instruction


class ConversationImageInputTest(unittest.TestCase):
    def test_render_history_as_html_expands_json_tool_result_content(self) -> None:
        conversation = Conversation()
        conversation.add_tool_call("call_1", '{"os": "Linux", "architecture": "x86_64"}')

        html = conversation.render_history_as_html()

        self.assertIn('"os": "Linux"', html)
        self.assertIn('"architecture": "x86_64"', html)
        self.assertNotIn(r'\"os\"', html)

    def test_render_history_as_html_renders_images_and_message_anchors(self) -> None:
        conversation = Conversation()
        conversation.add_user_message("请分析图片", images=["https://example.com/chart.png"])
        conversation.messages.append({"role": "assistant", "content": "这是分析结果。"})

        html = conversation.render_history_as_html()

        self.assertIn('id="message-1"', html)
        self.assertIn('href="#message-1">#1</a>', html)
        self.assertIn('id="message-2"', html)
        self.assertIn('href="#message-2">#2</a>', html)
        self.assertIn('<img src="https://example.com/chart.png"', html)
        self.assertIn("请分析图片", html)
        self.assertNotIn('&quot;type&quot;: &quot;image_url&quot;', html)

    def test_render_history_as_html_preserves_chinese_in_tool_details(self) -> None:
        conversation = Conversation()
        conversation.add_tool_call("call_1", '{"title": "中文测试"}')
        conversation.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "搜索", "arguments": '{"查询": "中文"}'},
                    }
                ],
            }
        )

        html = conversation.render_history_as_html()

        self.assertIn("中文测试", html)
        self.assertIn("搜索", html)
        self.assertIn("查询", html)
        self.assertNotIn(r"\u4e2d\u6587", html)

    def test_add_user_message_keeps_plain_text(self) -> None:
        conversation = Conversation()

        conversation.add_user_message("hello")

        self.assertEqual(conversation.messages[-1], {"role": "user", "content": "hello"})

    def test_add_user_message_supports_image_urls(self) -> None:
        conversation = Conversation()

        conversation.add_user_message(
            "compare them",
            images=["https://example.com/cat.png", "https://example.com/dog.png"],
        )

        self.assertEqual(
            conversation.messages[-1],
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "compare them"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
                    {"type": "image_url", "image_url": {"url": "https://example.com/dog.png"}},
                ],
            },
        )

    def test_add_user_message_encodes_local_file(self) -> None:
        conversation = Conversation()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            image_path.write_bytes(b"png-bytes")

            conversation.add_user_message("", images=[str(image_path)])

        content = cast(list[dict[str, Any]], cast(dict[str, Any], conversation.messages[-1])["content"])
        assert isinstance(content, list)
        image_url = content[0]["image_url"]["url"]
        self.assertEqual(
            image_url,
            f"data:image/png;base64,{base64.b64encode(b'png-bytes').decode('utf-8')}",
        )

    def test_history_stringifies_multimodal_user_content(self) -> None:
        conversation = Conversation()
        conversation.add_user_message("what is here", images=["https://example.com/cat.png"])

        history = conversation.to_history()

        self.assertEqual(history[-1]["role"], "user")
        self.assertIn('"type": "image_url"', history[-1]["content"])

    def test_add_user_message_preserves_image_order(self) -> None:
        conversation = Conversation()

        conversation.add_user_message(
            "first\nsecond",
            images=["https://example.com/cat.png"],
        )

        self.assertEqual(
            conversation.messages[-1],
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first\nsecond"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
                ],
            },
        )

    def test_pop_last_message_if_user_removes_multimodal_user_message(self) -> None:
        conversation = Conversation()
        conversation.add_user_message("describe this", images=["https://example.com/cat.png"])

        removed = conversation.pop_last_message_if_user()

        self.assertEqual(
            removed,
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
                ],
            },
        )
        self.assertEqual(conversation.messages, [])


class DisplayMessageInputTest(unittest.TestCase):
    def test_input_to_instruction_parses_images(self) -> None:
        instruction = input_to_instruction(
            "[image:https://example.com/cat.png image:https://example.com/dog.png] compare them"
        )

        self.assertEqual(
            instruction,
            MessageInstruction(
                content="compare them",
                images=["https://example.com/cat.png", "https://example.com/dog.png"],
            ),
        )

    def test_input_to_instruction_keeps_plain_text_when_not_image_syntax(self) -> None:
        instruction = input_to_instruction("[note:todo] compare them")

        self.assertEqual(
            instruction,
            MessageInstruction(content="[note:todo] compare them"),
        )


if __name__ == "__main__":
    unittest.main()