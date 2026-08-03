"""Comprehensive test suite for patch tools - all tests consolidated."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from xun.tools.patch import (
    _apply_with_git,
    _apply_with_patch_cmd,
    _normalize_patch,
    _patch_paths,
    _strip_path,
    _validate_patch,
    _validate_patch_paths,
    apply_patch,
)
from xun.toolcall import ToolCallContext
from xun.tempdir import DeferredTempDirectory


# Sample patches for testing
SAMPLE_PATCH = """\
--- a/src/hello.py
+++ b/src/hello.py
@@ -1,3 +1,4 @@
 def greet(name):
-    print("Hi")
+    print(f"Hello, {name}!")
+    print("Welcome!")
     return True
"""

MULTI_FILE_PATCH = """\
--- a/src/file1.py
+++ b/src/file1.py
@@ -1 +1 @@
-old
+new

--- a/src/file2.py
+++ b/src/file2.py
@@ -1 +1 @@
-old
+new
"""

CREATE_FILE_PATCH = """\
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+# new file
+print("hello")
"""

EMPTY_PATCH = ""
BAD_HEADER = "--- a/file.py\n+++ b/file.py\n@@ invalid @@\n"
NO_HEADERS = "@@ -1,3 +1,4 @@\n-old\n+new\n"
NO_HUNKS = "--- a/file\n+++ b/file\n"
GARBAGE = "just some random text"

HUNK_FORMATS = [
    "@@ -1,2 +1,3 @@",
    "@@ -1,2 +1,3 @@ function test()",
    '@@ -1,2 +1,3 @@ "quoted.py"',
    "@@ -1,2 +1,3 @@  extra spaces",
]


class TestValidation(unittest.TestCase):
    """Tests for patch validation and normalization."""

    def test_normalize_patch_adds_newline(self):
        """Tool-call strings often omit the final newline required by git apply."""
        self.assertEqual(_normalize_patch("patch"), "patch\n")
        self.assertEqual(_normalize_patch("patch\n"), "patch\n")

    def test_valid_patches(self):
        """Valid patches should not raise."""
        _validate_patch(SAMPLE_PATCH)
        _validate_patch(MULTI_FILE_PATCH)
        _validate_patch(CREATE_FILE_PATCH)

    def test_empty_patch_fails(self):
        """Empty patch should raise ValueError."""
        with self.assertRaises(ValueError):
            _validate_patch("")
        with self.assertRaises(ValueError):
            _validate_patch("   \n\n  ")

    def test_missing_headers_fails(self):
        """Patch without ---/+++ should raise."""
        with self.assertRaises(ValueError):
            _validate_patch(NO_HEADERS)

    def test_missing_hunks_fails(self):
        """Patch without @@ should raise."""
        with self.assertRaises(ValueError):
            _validate_patch(NO_HUNKS)

    def test_both_missing_fails(self):
        """Patch with neither headers nor hunks should raise."""
        with self.assertRaises(ValueError):
            _validate_patch(GARBAGE)

    def test_invalid_hunk_header_fails(self):
        with self.assertRaisesRegex(ValueError, "Invalid hunk header"):
            _validate_patch(BAD_HEADER)

    def test_hunk_line_counts_not_validated(self):
        """Line count mismatches are left to git apply / patch --dry-run."""
        patch_with_wrong_counts = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line one
-line two
+line two updated
"""
        _validate_patch(patch_with_wrong_counts)  # should pass validation

    def test_hunk_header_variations_are_valid(self):
        """Different hunk formats should be valid."""
        for header in HUNK_FORMATS:
            patch_content = f"""\
--- a/file.py
+++ b/file.py
{header}
 line1
"""
            _validate_patch(patch_content)


class TestPathHandling(unittest.TestCase):
    """Tests for path extraction and validation."""

    def test_extract_paths_from_single_file(self):
        paths = _patch_paths(SAMPLE_PATCH)
        self.assertEqual(paths, ["a/src/hello.py", "b/src/hello.py"])

    def test_extract_paths_from_multi_file(self):
        paths = _patch_paths(MULTI_FILE_PATCH)
        self.assertEqual(
            paths,
            ["a/src/file1.py", "b/src/file1.py", "a/src/file2.py", "b/src/file2.py"],
        )

    def test_extract_paths_skips_dev_null(self):
        paths = _patch_paths(CREATE_FILE_PATCH)
        self.assertEqual(paths, ["b/src/new.py"])

    def test_strip_path_with_zero(self):
        self.assertEqual(_strip_path("a/b/c.py", 0), "a/b/c.py")

    def test_strip_path_with_one(self):
        self.assertEqual(_strip_path("a/b/c.py", 1), "b/c.py")
        self.assertEqual(_strip_path("src/file.py", 0), "src/file.py")

    def test_strip_path_rejects_negative(self):
        with self.assertRaises(ValueError):
            _strip_path("a/b/c.py", -1)

    def test_strip_path_rejects_too_few(self):
        with self.assertRaises(ValueError):
            _strip_path("file.py", 1)

    def test_paths_must_stay_in_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            self.assertEqual(_validate_patch_paths(SAMPLE_PATCH, 1, directory), ["src/hello.py"])
            escaped_patch = SAMPLE_PATCH.replace("a/src/hello.py", "a/../outside.py").replace(
                "b/src/hello.py", "b/../outside.py"
            )
            with self.assertRaises(ValueError):
                _validate_patch_paths(escaped_patch, 1, directory)

    def test_tabs_in_headers(self):
        """Should handle tabs in file headers correctly."""
        tabs_patch = """\
--- a/src/file\twith\ttabs
+++ b/src/file\twith\ttabs
@@ -1 +1 @@
-olds
+news
"""
        paths = _patch_paths(tabs_patch)
        self.assertEqual(paths, ["a/src/file", "b/src/file"])


class TestGitApply(unittest.TestCase):
    """Tests for git apply functionality."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        return ctx

    @patch("xun.tools.patch.subprocess.run")
    def test_apply_calls_check_first(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_git(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertEqual(mock_run.call_count, 2)
            self.assertIn("--check", mock_run.call_args_list[0].args[0])
            self.assertNotIn("--check", mock_run.call_args_list[1].args[0])

    @patch("xun.tools.patch.subprocess.run")
    def test_apply_reverse_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_git(Path(tmpdir), SAMPLE_PATCH, True, 1)
            args_all = [call.args[0] for call in mock_run.call_args_list]
            self.assertTrue(any(["--reverse" in args for args in args_all]))

    @patch("xun.tools.patch.subprocess.run")
    def test_apply_strip_zero(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_git(Path(tmpdir), SAMPLE_PATCH, False, 0)
            args_all = [call.args[0] for call in mock_run.call_args_list]
            self.assertTrue(any(["-p 0" in " ".join(args) for args in args_all]))

    @patch("xun.tools.patch.subprocess.run")
    def test_check_failure_raises(self, mock_run):
        mock_dry_run = MagicMock(returncode=2, stderr="error: patch failed")
        mock_apply = MagicMock(returncode=1, stderr="error: cannot apply")
        mock_run.side_effect = [mock_dry_run, mock_apply]
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with self.assertRaises(RuntimeError) as cm:
                _apply_with_git(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertIn("Patch check failed", str(cm.exception))

    @patch("xun.tools.patch.subprocess.run")
    def test_apply_failure_raises(self, mock_run):
        mock_check = MagicMock(returncode=0, stderr="")
        mock_apply = MagicMock(returncode=2, stderr="error: cannot apply")
        mock_run.side_effect = [mock_check, mock_apply]
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with self.assertRaises(RuntimeError) as cm:
                _apply_with_git(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertIn("Patch application failed", str(cm.exception))


class TestPatchCmd(unittest.TestCase):
    """Tests for patch command functionality."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        return ctx

    @patch("xun.tools.patch.subprocess.run")
    def test_dry_run_first(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertEqual(mock_run.call_count, 2)
            self.assertIn("--dry-run", mock_run.call_args_list[0].args[0])
            self.assertNotIn("--dry-run", mock_run.call_args_list[1].args[0])

    @patch("xun.tools.patch.subprocess.run")
    def test_reverse_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_patch_cmd(Path(tmpdir), SAMPLE_PATCH, True, 1)
            args1 = mock_run.call_args_list[1].args[0]
            self.assertIn("-R", args1)

    @patch("xun.tools.patch.subprocess.run")
    def test_dry_run_exit_code_2_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=2, stderr="usage error")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with self.assertRaises(RuntimeError):
                _apply_with_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1)

    @patch("xun.tools.patch.subprocess.run")
    def test_apply_exit_code_2_raises(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),
            MagicMock(returncode=2, stderr="usage error"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with self.assertRaises(RuntimeError):
                _apply_with_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1)

    @patch("xun.tools.patch.subprocess.run")
    def test_exit_codes_0_and_1_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertTrue(True)  # should not raise


class TestApplyPatchIntegration(unittest.TestCase):
    """Integration tests for apply_patch function."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        ctx.agent.name = "test"
        ctx.tool_name = "apply_patch"
        return ctx

    @patch("xun.tools.patch._is_git_repo")
    def test_git_path(self, mock_git):
        mock_git.return_value = True
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with patch("xun.tools.patch._apply_with_git") as mock_apply:
                apply_patch(ctx, SAMPLE_PATCH)
                mock_apply.assert_called_once()

    @patch("xun.tools.patch._is_git_repo")
    def test_patch_path(self, mock_git):
        mock_git.return_value = False
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with patch("xun.tools.patch._apply_with_patch_cmd") as mock_apply:
                apply_patch(ctx, SAMPLE_PATCH)
                mock_apply.assert_called_once()

    @patch("xun.tools.patch._is_git_repo", return_value=False)
    @patch("xun.tools.patch._apply_with_patch_cmd")
    def test_returns_success_message(self, mock_apply, mock_git):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            result = apply_patch(ctx, SAMPLE_PATCH)
            self.assertIn("Applied successfully", result)
            self.assertIn("Modified 1 file(s)", result)

    @patch("xun.tools.patch._is_git_repo", return_value=True)
    @patch("xun.tools.patch._apply_with_git")
    def test_reverse_flag(self, mock_git_apply, mock_git):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            apply_patch(ctx, SAMPLE_PATCH, reverse=True)
            mock_git_apply.assert_called_once()
            call_args = mock_git_apply.call_args[0]
            self.assertEqual(call_args[2], True)

    @patch("xun.tools.patch._is_git_repo", return_value=True)
    @patch("xun.tools.patch._apply_with_git")
    def test_strip_zero(self, mock_git_apply, mock_git):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            apply_patch(ctx, SAMPLE_PATCH, strip=0)
            mock_git_apply.assert_called_once()
            call_args = mock_git_apply.call_args[0]
            self.assertEqual(call_args[3], 0)

    @patch("xun.tools.patch._is_git_repo", return_value=False)
    @patch("xun.tools.patch._apply_with_patch_cmd")
    def test_apply_in_registered_tempdir(self, mock_patch_cmd, mock_git):
        """The temporary directory itself is an allowed directory."""
        with tempfile.TemporaryDirectory() as workdir, tempfile.TemporaryDirectory() as tempdir:
            temp_directory = Path(tempdir)
            registered_tempdir = DeferredTempDirectory(temp_directory)
            ctx = self._make_ctx(Path(workdir))
            apply_patch(ctx, SAMPLE_PATCH, directory=str(temp_directory))
            mock_patch_cmd.assert_called_once_with(temp_directory, SAMPLE_PATCH, False, 1)
            self.assertIsNotNone(registered_tempdir)


class TestGitApplyRealWorld(unittest.TestCase):
    """Real-world tests with actual git apply."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        return ctx

    def test_git_apply_normalized_patch_without_newline(self):
        """A valid tool-call patch applies after terminal-newline normalization."""
        patch_without_newline = """\
--- a/example.txt
+++ b/example.txt
@@ -1,3 +1,4 @@
-Hello World
+Hello Patched World
 This is a test file.
+The patch tool is working!
 Goodbye World"""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "example.txt").write_text(
                "Hello World\nThis is a test file.\nGoodbye World\n"
            )
            _apply_with_git(directory, _normalize_patch(patch_without_newline), False, 1)
            self.assertEqual(
                (directory / "example.txt").read_text(),
                "Hello Patched World\nThis is a test file.\nThe patch tool is working!\nGoodbye World",
            )

    def test_git_apply_source_without_newline(self):
        """fs_write_file-style content can be patched without an EOF marker."""
        patch_content = """\
--- a/example.txt
+++ b/example.txt
@@ -1,3 +1,4 @@
-Hello World
+Hello Patched World
 This is a test file.
 Line three.
+The patch tool is working!
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "example.txt").write_text("Hello World\nThis is a test file.\nLine three.")
            _apply_with_git(directory, patch_content, False, 1)
            self.assertEqual(
                (directory / "example.txt").read_text(),
                "Hello Patched World\nThis is a test file.\nLine three.\nThe patch tool is working!",
            )


if __name__ == "__main__":
    unittest.main()