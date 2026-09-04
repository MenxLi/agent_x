"""Tests for patch tools - end-to-end against real files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from xun.tools.patch import (
    _extract_paths,
    _generate_patch,
    _validate_patch,
    apply_patch,
    apply_patch_from_files,
)
from xun.toolcall import ToolCallContext

SAMPLE_PATCH = """\
--- a/hello.py
+++ b/hello.py
@@ -1,3 +1,4 @@
 def greet(name):
-    print("Hi")
+    print(f"Hello, {name}!")
+    print("Welcome!")
     return True
"""

ORIGINAL = 'def greet(name):\n    print("Hi")\n    return True\n'
GARBAGE = "just text"


def make_ctx(workdir: Path) -> MagicMock:
    ctx = MagicMock(spec=ToolCallContext)
    ctx.agent.workdir = workdir
    ctx.agent.tempdir.exist_path = None
    return ctx


class TestValidation(unittest.TestCase):
    def test_valid_patch(self):
        _validate_patch(SAMPLE_PATCH)

    def test_empty_patch_raises(self):
        with self.assertRaises(ValueError):
            _validate_patch("")
        with self.assertRaises(ValueError):
            _validate_patch("   \n\n  ")

    def test_missing_headers_raises(self):
        with self.assertRaises(ValueError):
            _validate_patch("--- header only")

    def test_invalid_hunk_header_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid hunk header"):
            _validate_patch("--- a/file\n+++ b/file\n@@ invalid @@\n")


class TestGeneratePatch(unittest.TestCase):
    def test_no_doubled_newlines(self):
        patch = _generate_patch(
            "line1\nline2\nline3\n",
            "line1\nline2 changed\nline3\nline4\n",
            "a/f.py", "b/f.py",
        )
        for line in patch.splitlines():
            self.assertTrue(line.strip(), f"blank line in generated patch:\n{patch!r}")

    def test_generated_patch_is_applyable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            old = "line1\nline2\nline3\n"
            new = "line1\nline2 changed\nline3\nline4\n"
            patch = _generate_patch(old, new, "a/f.py", "b/f.py")
            (d / "f.py").write_text(old)
            apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertEqual((d / "f.py").read_text(), new)

    def test_generated_multiline_patch_is_applyable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            old = "".join(f"line{i}\n" for i in range(1, 31))
            new = old.replace("line5", "LINE5").replace("line25", "LINE25")
            patch = _generate_patch(old, new, "a/big.py", "b/big.py")
            (d / "big.py").write_text(old)
            apply_patch(make_ctx(d), patch, directory=str(d))
            self.assertEqual((d / "big.py").read_text(), new)

    def test_identical_content_is_empty(self):
        self.assertEqual(_generate_patch("same\n", "same\n", "a/f", "b/f"), "")


class TestApplyPatch(unittest.TestCase):
    def _setup(self, tmpdir: str) -> tuple[MagicMock, Path]:
        d = Path(tmpdir)
        (d / "hello.py").write_text(ORIGINAL)
        return make_ctx(d), d

    def test_apply_and_verify_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            result = apply_patch(ctx, SAMPLE_PATCH, directory=str(d))
            self.assertIn("Applied successfully", result)
            self.assertIn("hello.py", result)
            self.assertEqual(
                (d / "hello.py").read_text(),
                'def greet(name):\n    print(f"Hello, {name}!")\n    print("Welcome!")\n    return True\n',
            )

    def test_reverse(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            apply_patch(ctx, SAMPLE_PATCH, directory=str(d))
            apply_patch(ctx, SAMPLE_PATCH, reverse=True, directory=str(d))
            self.assertEqual((d / "hello.py").read_text(), ORIGINAL)

    def test_failing_patch_leaves_files_untouched(self):
        """A partially matching patch must never leave files half-modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            patch = (
                "--- a/hello.py\n"
                "+++ b/hello.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def greet(name):\n"
                '-    print("Hi")\n'
                '+    print("Bye")\n'
                "@@ -10,3 +10,3 @@\n"
                " nonexistent context\n"
                "-nope\n"
                "+yep\n"
            )
            with self.assertRaisesRegex(RuntimeError, "Patch application failed"):
                apply_patch(ctx, patch, directory=str(d))
            self.assertEqual((d / "hello.py").read_text(), ORIGINAL)
            rejects = list(d.glob("*.rej")) + list(d.glob("*.orig"))
            self.assertEqual(rejects, [])

    def test_error_message_includes_hunk_detail(self):
        """Failure must surface the real reason (patch prints on stdout), not bare 'Patch failed'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            patch = (
                "--- a/hello.py\n"
                "+++ b/hello.py\n"
                "@@ -1,2 +1,2 @@\n"
                " wrong context\n"
                "-nope\n"
                "+yep\n"
            )
            with self.assertRaises(RuntimeError) as cm:
                apply_patch(ctx, patch, directory=str(d))
            msg = str(cm.exception)
            self.assertIn("FAILED", msg)
            self.assertIn("Re-read the target file", msg)

    def test_already_applied_patch_rejected(self):
        """Applying the same patch twice must fail clearly, not reverse-apply."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            apply_patch(ctx, SAMPLE_PATCH, directory=str(d))
            with self.assertRaises(RuntimeError):
                apply_patch(ctx, SAMPLE_PATCH, directory=str(d))
            # still the applied version, not reverted
            self.assertIn("Welcome!", (d / "hello.py").read_text())

    def test_offset_apply_warns(self):
        """Patch whose content moved (offset) should apply and warn to verify."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            (d / "hello.py").write_text("import sys\nimport os\n\n\n" + ORIGINAL)
            result = apply_patch(ctx, SAMPLE_PATCH, directory=str(d))
            self.assertIn("Applied successfully", result)
            self.assertIn("Warning", result)
            self.assertIn("Welcome!", (d / "hello.py").read_text())

    def test_garbage_patch_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            with self.assertRaises(ValueError):
                apply_patch(ctx, GARBAGE, directory=str(d))

    def test_new_file_via_dev_null(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx, d = self._setup(tmpdir)
            patch = (
                "--- /dev/null\n"
                "+++ b/new.py\n"
                "@@ -0,0 +1,2 @@\n"
                "+x = 1\n"
                "+y = 2\n"
            )
            result = apply_patch(ctx, patch, directory=str(d))
            self.assertIn("Applied successfully", result)
            # /dev/null must not be counted as a modified file
            self.assertIn("1 file(s)", result)
            self.assertEqual((d / "new.py").read_text(), "x = 1\ny = 2\n")


class TestExtractPaths(unittest.TestCase):
    def test_skips_dev_null(self):
        patch = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _extract_paths(patch, 1, Path(tmpdir))
        self.assertEqual(paths, ["new.py"])

    def test_strips_prefix(self):
        patch = "--- a/src/x.py\n+++ b/src/x.py\n@@\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _extract_paths(patch, 1, Path(tmpdir))
        self.assertEqual(paths, ["src/x.py"])


class TestApplyPatchFromFiles(unittest.TestCase):
    def test_end_to_end(self):
        """The generated patch must actually apply and produce the new content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            source = d / "current.txt"
            target = d / "target.txt"
            source.write_text("A\nB\nC\n")  # what the target currently contains
            target.write_text("A\nB\nC\n")

            ctx = make_ctx(d)
            result = apply_patch_from_files(
                ctx=ctx,
                source_path=str(source),
                target_path=str(target),
                target_content="A\nB\nC\nD\nE\n",
                directory=str(d),
            )
            self.assertIn("Applied successfully", result)
            self.assertEqual(target.read_text(), "A\nB\nC\nD\nE\n")

    def test_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "sub").mkdir()
            (d / "sub" / "cur.txt").write_text("one\ntwo\n")
            ctx = make_ctx(d)
            result = apply_patch_from_files(
                ctx=ctx,
                source_path="sub/cur.txt",
                target_path="sub/cur.txt",
                target_content="one\nTWO\nthree\n",
                directory=str(d),
            )
            self.assertIn("Applied successfully", result)
            self.assertIn("sub/cur.txt", result)
            self.assertEqual((d / "sub" / "cur.txt").read_text(), "one\nTWO\nthree\n")

    def test_identical_content_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "a.txt").write_text("same\n")
            (d / "b.txt").write_text("same\n")
            ctx = make_ctx(d)
            result = apply_patch_from_files(
                ctx=ctx, source_path="a.txt", target_path="b.txt", directory=str(d)
            )
            self.assertIn("No changes", result)

    def test_source_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            ctx = make_ctx(d)
            with self.assertRaises(FileNotFoundError):
                apply_patch_from_files(
                    ctx=ctx, source_path="nonexistent.py",
                    target_path="target.py", directory=str(d),
                )

    def test_missing_target_path_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "src.txt").write_text("x\n")
            ctx = make_ctx(d)
            with self.assertRaises(ValueError):
                apply_patch_from_files(ctx=ctx, source_path="src.txt", directory=str(d))


if __name__ == "__main__":
    unittest.main()
