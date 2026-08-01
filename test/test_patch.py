import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from xun.tools.patch import _apply_with_git, _normalize_patch, _patch_paths, _strip_path, _validate_patch, _validate_patch_paths, apply_patch
from xun.toolcall import ToolCallContext
from xun.tempdir import DeferredTempDirectory


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


class TestValidatePatch(unittest.TestCase):
    def test_normalize_patch_adds_terminal_newline(self):
        """Tool-call strings often omit the final newline required by git apply."""
        self.assertEqual(_normalize_patch("patch"), "patch\n")
        self.assertEqual(_normalize_patch("patch\n"), "patch\n")

    def test_valid_patch(self):
        """Valid patches should not raise."""
        _validate_patch(SAMPLE_PATCH)
        _validate_patch(MULTI_FILE_PATCH)
        _validate_patch(CREATE_FILE_PATCH)

    def test_empty_patch(self):
        """Empty patch should raise ValueError."""
        with self.assertRaises(ValueError, msg="Patch content is empty"):
            _validate_patch("")
        with self.assertRaises(ValueError, msg="Patch content is empty"):
            _validate_patch("   \n\n  ")

    def test_missing_file_headers(self):
        """Patch without ---/+++ should raise."""
        bad = "@@ -1,3 +1,4 @@\n-old\n+new\n"
        with self.assertRaises(ValueError):
            _validate_patch(bad)

    def test_missing_hunk_markers(self):
        """Patch without @@ should raise."""
        bad = "--- a/file\n+++ b/file\n"
        with self.assertRaises(ValueError):
            _validate_patch(bad)

    def test_both_missing(self):
        """Patch with neither headers nor hunks should raise."""
        with self.assertRaises(ValueError):
            _validate_patch("just some text")

    def test_invalid_hunk_line_counts(self):
        """Declared hunk counts must match its context, removed, and added lines."""
        corrupt_patch = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line one
-line two
+line two updated
"""
        with self.assertRaisesRegex(ValueError, r"declares -3 \+3 lines, but contains -2 \+2"):
            _validate_patch(corrupt_patch)

    def test_invalid_hunk_header(self):
        bad_header = "--- a/file.py\n+++ b/file.py\n@@ invalid @@\n"
        with self.assertRaisesRegex(ValueError, "Invalid hunk header"):
            _validate_patch(bad_header)


class TestPatchPaths(unittest.TestCase):
    def test_single_file(self):
        paths = _patch_paths(SAMPLE_PATCH)
        self.assertEqual(paths, ["a/src/hello.py", "b/src/hello.py"])

    def test_multi_file(self):
        paths = _patch_paths(MULTI_FILE_PATCH)
        self.assertEqual(
            paths,
            ["a/src/file1.py", "b/src/file1.py", "a/src/file2.py", "b/src/file2.py"],
        )

    def test_create_file(self):
        """The /dev/null source of a new file should be skipped."""
        paths = _patch_paths(CREATE_FILE_PATCH)
        self.assertEqual(paths, ["b/src/new.py"])

    def test_strip_path(self):
        self.assertEqual(_strip_path("a/src/file.py", 1), "src/file.py")
        self.assertEqual(_strip_path("src/file.py", 0), "src/file.py")

    def test_strip_path_rejects_invalid_strip(self):
        with self.assertRaises(ValueError):
            _strip_path("file.py", 1)
        with self.assertRaises(ValueError):
            _strip_path("a/file.py", -1)

    def test_paths_must_stay_in_patch_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            self.assertEqual(_validate_patch_paths(SAMPLE_PATCH, 1, directory), ["src/hello.py"])
            escaped_patch = SAMPLE_PATCH.replace("a/src/hello.py", "a/../outside.py").replace(
                "b/src/hello.py", "b/../outside.py"
            )
            with self.assertRaises(ValueError):
                _validate_patch_paths(escaped_patch, 1, directory)


class TestApplyPatch(unittest.TestCase):
    def _make_ctx(self, workdir: Path, is_git: bool = True) -> ToolCallContext:
        """Create a mock ToolCallContext."""
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        ctx.agent.name = "test-agent"
        ctx.tool_name = "apply_patch"
        return ctx

    @patch("xun.tools.patch._is_git_repo")
    @patch("xun.tools.patch._apply_with_git")
    def test_apply_in_git_repo(self, mock_git, mock_is_git):
        """Should call git apply when in a git repo."""
        mock_is_git.return_value = True
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            apply_patch(ctx, SAMPLE_PATCH)
            mock_git.assert_called_once()
            mock_git.assert_any_call(Path(tmpdir), SAMPLE_PATCH, False, 1)

    @patch("xun.tools.patch._is_git_repo")
    @patch("xun.tools.patch._apply_with_patch_cmd")
    def test_apply_in_non_git_repo(self, mock_patch_cmd, mock_is_git):
        """Should fall back to patch command when not in a git repo."""
        mock_is_git.return_value = False
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            apply_patch(ctx, SAMPLE_PATCH)
            mock_patch_cmd.assert_called_once()
            mock_patch_cmd.assert_any_call(Path(tmpdir), SAMPLE_PATCH, False, 1)

    def test_return_value(self):
        """Return value should report file count."""
        with patch("xun.tools.patch._is_git_repo", return_value=False):
            with patch("xun.tools.patch._apply_with_patch_cmd"):
                with tempfile.TemporaryDirectory() as tmpdir:
                    ctx = self._make_ctx(Path(tmpdir))
                    result = apply_patch(ctx, SAMPLE_PATCH)
                    self.assertIn("src/hello.py", result)
                    self.assertIn("Modified 1 file(s)", result)

    def test_reverse_flag(self):
        """reverse=True should pass through."""
        with patch("xun.tools.patch._is_git_repo", return_value=True):
            with patch("xun.tools.patch._apply_with_git") as mock:
                with tempfile.TemporaryDirectory() as tmpdir:
                    ctx = self._make_ctx(Path(tmpdir))
                    apply_patch(ctx, SAMPLE_PATCH, reverse=True)
                    mock.assert_called_with(Path(tmpdir), SAMPLE_PATCH, True, 1)

    def test_apply_in_registered_tempdir(self):
        """The temporary directory itself, not only its children, is an allowed directory."""
        with tempfile.TemporaryDirectory() as workdir, tempfile.TemporaryDirectory() as tempdir:
            temp_directory = Path(tempdir)
            registered_tempdir = DeferredTempDirectory(temp_directory)
            ctx = self._make_ctx(Path(workdir))
            with patch("xun.tools.patch._is_git_repo", return_value=False):
                with patch("xun.tools.patch._apply_with_patch_cmd") as mock_patch_cmd:
                    apply_patch(ctx, SAMPLE_PATCH, directory=str(temp_directory))
                    mock_patch_cmd.assert_called_once_with(temp_directory, SAMPLE_PATCH, False, 1)
            self.assertIsNotNone(registered_tempdir)

    @patch("xun.tools.patch.subprocess.run")
    def test_git_apply_uses_supported_strip_option(self, mock_run):
        """git apply accepts -p <number> and tolerates a missing source-file newline."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            _apply_with_git(Path(tmpdir), SAMPLE_PATCH, False, 0)

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(
            mock_run.call_args_list[0].args[0],
            ["git", "apply", "--inaccurate-eof", "-p", "0", "--check"],
        )
        self.assertEqual(
            mock_run.call_args_list[1].args[0],
            ["git", "apply", "--inaccurate-eof", "-p", "0"],
        )

    def test_git_apply_accepts_normalized_patch_without_terminal_newline(self):
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

    def test_git_apply_accepts_source_without_terminal_newline(self):
        """fs_write_file-style content can be patched without an EOF marker."""
        patch = """\
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
            _apply_with_git(directory, patch, False, 1)
            self.assertEqual(
                (directory / "example.txt").read_text(),
                "Hello Patched World\nThis is a test file.\nLine three.\nThe patch tool is working!",
            )


if __name__ == "__main__":
    unittest.main()