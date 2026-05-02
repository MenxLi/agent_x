import unittest
from xun.tools.cmd import _confirmation_policy, _parse_command_spec


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
            "echo $(pwd)",
            "echo $(ls | wc)",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, False)

    def test_exact_safe_redirections_are_auto_approved(self) -> None:
        for command in (
            "ls 2>&1",
            "ls >/dev/null",
            "ls 1>/dev/null",
            "ls 2>/dev/null",
            "ls >/dev/null 2>&1",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, False)

    def test_chain_with_non_allowlisted_command_requires_confirmation(self) -> None:
        for command in (
            "ls && rm",
            "ls | rm",
            "ls ; rm",
            "echo $(rm)",
            "echo hi 2>&11",
            "echo hi 2>/dev/nullx",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_unsupported_shell_syntax_requires_confirmation(self) -> None:
        for command in (
            "ls > out.txt",
            "ls 2>&2",
            "ls 1>&2",
            "ls >>/dev/null",
            "ls </dev/null",
            "ls &",
            "ls\npwd",
            "echo `pwd`",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_path_based_commands_require_confirmation(self) -> None:
        for command in (
            "/bin/ls",
            "./script.sh",
            "echo $(/bin/ls)",
        ):
            with self.subTest(command=command):
                self.assertConfirmationRequired(command, True)

    def test_parse_collects_all_command_heads(self) -> None:
        spec = _parse_command_spec("(ls | wc) && echo ok")
        self.assertEqual([command.value for command in spec.commands], ["ls", "wc", "echo"])


if __name__ == "__main__":
    unittest.main()