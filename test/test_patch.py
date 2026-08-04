"""Tests for patch tools - simplified and focused."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from xun.tools.patch import (
    _apply_patch_cmd,
    _generate_patch,
    _validate_patch,
    apply_patch,
    apply_patch_from_files,
    _enhance_patch_error,
)
from xun.toolcall import ToolCallContext


# Sample patches
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

EMPTY = ""
BAD_FORMAT = "--- header only"
GARBAGE = "just text"


class TestValidation(unittest.TestCase):
    """Test patch validation."""

    def test_valid_patch(self):
        """Valid patches should not raise."""
        _validate_patch(SAMPLE_PATCH)

    def test_empty_patch_raises(self):
        """Empty patch should raise ValueError."""
        with self.assertRaises(ValueError):
            _validate_patch(EMPTY)
        with self.assertRaises(ValueError):
            _validate_patch("   \n\n  ")

    def test_missing_headers_raises(self):
        """Patch without ---/+++ should raise."""
        with self.assertRaises(ValueError):
            _validate_patch(BAD_FORMAT)

    def test_invalid_hunk_header_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid hunk header"):
            _validate_patch("--- a/file\n+++ b/file\n@@ invalid @@\n")

    def test_hunk_counts_not_validated(self):
        """Line count mismatches allowed by validation."""
        patch_with_wrong_counts = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line one
-line two
+line two updated
"""
        _validate_patch(patch_with_wrong_counts)  # should pass validation


class TestPatchError(unittest.TestCase):
    """Test error enhancement."""

    def test_enhanced_error_message(self):
        """Error message should include helpful tip."""
        stderr = "corrupt patch at line 7"
        enhanced = _enhance_patch_error(stderr)
        self.assertIn("Tip:", enhanced)
        self.assertIn("apply_patch_from_files", enhanced)


class TestApplyPatchCmd(unittest.TestCase):
    """Test patch command wrapper."""

    @patch("xun.tools.patch.subprocess.run")
    def test_fuzz_flag_preserves_success(self, mock_run):
        """Both with and without fuzz should work."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            for fuzz in (False, True):
                _apply_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1, fuzz=fuzz)
                args = mock_run.call_args[0][0]
                # Check that patch command is called with appropriate args
                self.assertEqual(args[:2], ["patch", "-p"])
                self.assertEqual(args[2], "1")
                self.assertIn("--no-backup-if-mismatch", args)
                if fuzz:
                    self.assertIn("--fuzz=5", args)
                else:
                    self.assertNotIn("--fuzz=5", args)

    @patch("xun.tools.patch.subprocess.run")
    def test_reverse_flag(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            _apply_patch_cmd(Path(tmpdir), SAMPLE_PATCH, True, 1)
            args = mock_run.call_args[0][0]
            self.assertIn("-R", args)

    @patch("xun.tools.patch.subprocess.run")
    def test_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="patch failed")
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as cm:
                _apply_patch_cmd(Path(tmpdir), SAMPLE_PATCH, False, 1)
            self.assertIn("Patch application failed", str(cm.exception))


class TestPatchGeneration(unittest.TestCase):
    """Test patch generation from files."""

    def test_generate_patch_creates_valid_diff(self):
        patch_content = _generate_patch("old content", "new content", "a/file.txt", "b/file.txt")
        _validate_patch(patch_content)
        self.assertIn("a/file.txt", patch_content)
        self.assertIn("b/file.txt", patch_content)


class TestApplyPatchIntegration(unittest.TestCase):
    """Integration tests for apply_patch."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        return ctx

    @patch("xun.tools.patch._is_git_repo")
    def test_uses_git_when_git_repo(self, mock_is_git):
        mock_is_git.return_value = True
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with patch("xun.tools.patch._apply_patch_cmd") as mock_apply:
                apply_patch(ctx, SAMPLE_PATCH, directory=tmpdir)
                mock_apply.assert_called_once()

    @patch("xun.tools.patch._is_git_repo")
    def test_uses_patch_when_not_git(self, mock_is_git):
        mock_is_git.return_value = False
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            with patch("xun.tools.patch._apply_patch_cmd") as mock_apply:
                apply_patch(ctx, SAMPLE_PATCH, directory=tmpdir)
                mock_apply.assert_called_once()

    @patch("xun.tools.patch._is_git_repo", return_value=False)
    @patch("xun.tools.patch._apply_patch_cmd")
    def test_returns_success_message(self, mock_apply, mock_is_git):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(Path(tmpdir))
            result = apply_patch(ctx, SAMPLE_PATCH)
            self.assertIn("Applied successfully", result)


class TestApplyPatchFromFiles(unittest.TestCase):
    """Tests for apply_patch_from_files."""

    def _make_ctx(self, workdir: Path) -> MagicMock:
        ctx = MagicMock(spec=ToolCallContext)
        ctx.agent.workdir = workdir
        return ctx

    @patch("xun.tools.patch._apply_patch_cmd")
    @patch("xun.tools.patch._is_git_repo")
    def test_apply_changes_file_to_file(self, mock_is_git, mock_apply):
        mock_is_git.return_value = False
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            source = tmpdir / "source.py"
            target = tmpdir / "target.py"
            source.write_text("def old():\n    pass\n")
            target.write_text("def new():\n    pass\n")  # Different content

            ctx = self._make_ctx(tmpdir)
            # Mock patch application to succeed
            mock_apply.return_value = None
            result = apply_patch_from_files(
                ctx=ctx,
                source_path=str(source),
                target_path=str(target),
                directory=str(tmpdir),
            )

            self.assertIn("Applied successfully", result)
            mock_apply.assert_called_once()

    def test_source_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            ctx = self._make_ctx(tmpdir)
            with self.assertRaises(FileNotFoundError):
                apply_patch_from_files(
                    ctx=ctx,
                    source_path="nonexistent.py",
                    target_path="target.py",
                    directory=str(tmpdir),
                )


if __name__ == "__main__":
    unittest.main()