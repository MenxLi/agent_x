"""Diagnostics of the patch tool: errors must say what patch(1) tripped on."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from xun.tools.patch import apply_patch
from xun.toolcall import ToolCallContext

ORIGINAL = 'def greet(name):\n    print("Hi")\n    return True\n'
SAMPLE_PATCH = (
    "--- a/hello.py\n"
    "+++ b/hello.py\n"
    "@@ -1,3 +1,4 @@\n"
    " def greet(name):\n"
    '-    print("Hi")\n'
    '+    print(f"Hello, {name}!")\n'
    '+    print("Welcome!")\n'
    "     return True\n"
)


def make_ctx(workdir: Path) -> MagicMock:
    ctx = MagicMock(spec=ToolCallContext)
    ctx.agent.workdir = workdir
    ctx.agent.tempdir.exist_path = None
    return ctx


class TestFailureHints(unittest.TestCase):
    """The advice appended to a failure must match the failure patch(1) reported."""

    def test_bare_paths_point_at_strip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "sub").mkdir()
            (d / "sub" / "f.py").write_text("a\nb\n")
            patch = "--- sub/f.py\n+++ sub/f.py\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("strip=0", str(cm.exception))

    def test_already_applied_points_at_reverse(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "hello.py").write_text(ORIGINAL)
            apply_patch(make_ctx(d), SAMPLE_PATCH, directory=str(d))
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), SAMPLE_PATCH, directory=str(d))
            self.assertIn("reverse=true", str(cm.exception))
            # the generic "regenerate the patch" advice must not compete with it
            self.assertNotIn("Re-read the target file", str(cm.exception))

    def test_traversal_points_at_patch_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            patch = "--- /dev/null\n+++ b/../../escaped.txt\n@@ -0,0 +1 @@\n+x\n"
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("inside the patch directory", str(cm.exception))

    def test_miscounted_hunk_points_at_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "f.py").write_text("a\nb\nc\n")
            (d / "g.py").write_text("x\n")
            # hunk #1 promises 4 old lines but delivers 2, so the next header is eaten
            patch = (
                "--- a/f.py\n+++ b/f.py\n@@ -1,4 +1,3 @@\n a\n-b\n+B\n"
                "--- a/g.py\n+++ b/g.py\n@@ -1,1 +1,1 @@\n-x\n+X\n"
            )
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("line counts", str(cm.exception))

    def test_missing_final_newline_explained_then_fixable(self):
        """A file whose last line has no newline needs the marker, and says so."""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "note.txt").write_text("a\nb")
            plain = "--- a/note.txt\n+++ b/note.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), plain, directory=str(d))
            self.assertIn("No newline at end of file", str(cm.exception))

            marked = (
                "--- a/note.txt\n+++ b/note.txt\n@@ -1,2 +1,2 @@\n a\n-b\n"
                "\\ No newline at end of file\n+c\n\\ No newline at end of file\n"
            )
            self.assertIn("Applied successfully",
                          apply_patch(make_ctx(d), marked, directory=str(d)))
            self.assertEqual((d / "note.txt").read_text(), "a\nc")

    def test_plain_hunk_failure_keeps_generic_advice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "hello.py").write_text(ORIGINAL)
            patch = "--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n nope\n-nope\n+yep\n"
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("Re-read the target file", str(cm.exception))


class TestPatchTargets(unittest.TestCase):
    def test_created_and_deleted_are_not_called_modified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "old.txt").write_text("x\n")
            patch = (
                "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+hi\n"
                "--- a/old.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
            )
            result = apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("Created 1 file(s): new.py", result)
            self.assertIn("Deleted 1 file(s): old.txt", result)
            self.assertNotIn("Modified", result)
            self.assertFalse((d / "old.txt").exists())
            self.assertEqual((d / "new.py").read_text(), "hi\n")

    def test_git_quoted_name_is_decoded_in_the_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "café.txt").write_text("cafe\n")
            patch = ('--- "a/caf\\303\\251.txt"\n+++ "b/caf\\303\\251.txt"\n'
                     '@@ -1 +1,2 @@\n cafe\n+au lait\n')
            result = apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("café.txt", result)
            self.assertEqual((d / "café.txt").read_text(), "cafe\nau lait\n")

    def test_rename_only_diff_is_named_as_unsupported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            patch = ("diff --git a/old.py b/new.py\nsimilarity index 100%\n"
                     "rename from old.py\nrename to new.py\n")
            with self.assertRaisesRegex(ValueError, "git apply"):
                apply_patch(make_ctx(d), patch, directory=str(d))

    def test_missing_directory_says_so(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "f.py").write_text("a\n")
            patch = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-a\n+A\n"
            with self.assertRaisesRegex(ValueError, "does not exist"):
                apply_patch(make_ctx(d), patch, directory=str(d / "gone"))


class TestFuzzPolicy(unittest.TestCase):
    def test_offset_still_applies_without_fuzz(self):
        """Moved content is an offset, not a context mismatch: exact match must work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "hello.py").write_text("import sys\nimport os\n\n\n" + ORIGINAL)
            result = apply_patch(make_ctx(d), SAMPLE_PATCH, directory=str(d))
            self.assertIn("Applied successfully", result)
            self.assertIn("Warning", result)
            self.assertIn("Welcome!", (d / "hello.py").read_text())

    def test_mismatching_context_still_applies_and_warns(self):
        """The relaxed fallback keeps working after the strict first attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "t.py").write_text("def test_x():\n    v = 1\n    assert v\n")
            patch = ("--- a/t.py\n+++ b/t.py\n@@ -1,3 +1,5 @@\n def test_x():\n"
                     "    v = 9\n     assert v\n+def test_y():\n+    pass\n")
            result = apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertIn("Applied successfully", result)
            self.assertIn("Warning", result)
            self.assertIn("def test_y", (d / "t.py").read_text())
            self.assertIn("    v = 1", (d / "t.py").read_text())


if __name__ == "__main__":
    unittest.main()
