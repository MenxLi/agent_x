import unittest
from agent_x.tools.cmd import _confirmation_policy, _parse_command_spec


class CmdConfirmationPolicyTest(unittest.TestCase):
    def assertConfirmationRequired(self, command: str, expected: bool) -> None:
        policy = _confirmation_policy(_parse_command_spec(command))
        self.assertIs(policy.requires_confirmation, expected, command)

    def test_allowlisted_command_chain_is_auto_approved(self) -> None:
        for command in (
            "ls && pwd",
            "(ls && pwd) || echo ok",
            "ls ; pwd",
            "ls | wc",
            "ls | wc && echo ok",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, False)

    def test_chain_with_non_allowlisted_command_requires_confirmation(self) -> None:
        for command in (
            "ls && rm",
            "ls | rm",
            "ls ; rm",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_unsupported_shell_syntax_requires_confirmation(self) -> None:
        for command in (
            "ls > out.txt",
            "ls &",
            "ls\npwd",
            "echo $(pwd)",
            "echo `pwd`",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_path_based_commands_require_confirmation(self) -> None:
        for command in (
            "/bin/ls",
            "./script.sh",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_parse_collects_all_command_heads(self) -> None:
        spec = _parse_command_spec("(ls | wc) && echo ok")
        self.assertEqual([command.value for command in spec.commands], ["ls", "wc", "echo"])


if __name__ == "__main__":
    unittest.main()