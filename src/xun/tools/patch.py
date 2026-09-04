from pathlib import Path
import re
from typing import Callable
import subprocess
from difflib import unified_diff
from .common import resolve_path
from ..toolcall import ToolCallContext

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _normalize_patch(patch: str) -> str:
    """Ensure patch ends with a newline."""
    return patch if patch.endswith("\n") else f"{patch}\n"


def _combined_output(result: subprocess.CompletedProcess) -> str:
    """patch reports hunk failures on stdout, so always merge both streams."""
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


def _failure_hint() -> str:
    return (
        "Common causes: the target file changed since the patch was created, "
        "or the patch's line numbers/context lines are wrong. "
        "Re-read the target file and regenerate the patch against its current content."
    )


def _run_patch(
    directory: Path,
    patch: str,
    reverse: bool,
    strip: int,
    fuzz: bool,
    dry_run: bool,
) -> subprocess.CompletedProcess:
    """Run the `patch` command in non-interactive mode."""
    args = ["patch", "-p", str(strip), "--batch", "--no-backup-if-mismatch"]
    if not reverse:
        # refuse already-applied patches instead of prompting to reverse them
        args.append("--forward")
    if dry_run:
        args.append("--dry-run")
    if fuzz:
        args.append("--fuzz=3")
    if reverse:
        args.append("-R")

    return subprocess.run(
        args,
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _validate_patch(patch: str) -> None:
    """Validate patch is a proper unified diff."""
    if not patch.strip():
        raise ValueError("Patch content is empty.")

    has_file_header = "--- " in patch and "+++ " in patch
    has_hunk = "@@" in patch
    if not (has_file_header and has_hunk):
        missing = []
        if not has_file_header:
            missing.append("'--- ' / '+++ ' headers")
        if not has_hunk:
            missing.append("'@@' hunk markers")
        raise ValueError(f"Invalid patch format. Missing: {', '.join(missing)}")

    # Validate hunk headers
    for i, line in enumerate(patch.splitlines(), 1):
        if line.startswith("@@"):
            if not _HUNK_HEADER.match(line):
                raise ValueError(f"Invalid hunk header at line {i}: {line!r}")


def _generate_patch(from_content: str, to_content: str, old_path: str, new_path: str) -> str:
    """Generate a unified diff patch."""
    # content lines keep their trailing newline; lineterm adds the newline the
    # ---/+++ headers need, so a plain join yields exactly one newline per line
    from_lines = from_content.splitlines(keepends=True)
    to_lines = to_content.splitlines(keepends=True)

    diff = unified_diff(
        from_lines, to_lines,
        fromfile=old_path, tofile=new_path,
        lineterm="\n",
    )
    patch = "".join(diff)
    return patch if patch.endswith("\n") or not patch else patch + "\n"


def _extract_paths(patch: str, strip: int, directory: Path) -> list[str]:
    """Extract and validate paths in the patch."""
    paths = set()
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        path = line[3:].lstrip().split("\t", 1)[0].strip()
        if path == "/dev/null" or not path:
            continue
        # mirror what `patch -pN` does: drop the first N path components
        parts = path.split("/")
        if len(parts) > strip:
            target = "/".join(parts[strip:])
            resolved = (directory / target).resolve()
            if resolved.is_relative_to(directory):
                paths.add(target)
    return sorted(paths)


def apply_patch(
    ctx: ToolCallContext,
    patch: str,
    reverse: bool = False,
    strip: int = 1,
    directory: str = ".",
) -> str:
    """Apply a unified diff patch.

    The patch is always dry-run first, so a failing patch never leaves files
    half-modified. If the exact match fails, a second attempt is made with
    fuzz (tolerating small context offsets) and the result is flagged.
    """
    patch = _normalize_patch(patch)
    _validate_patch(patch)

    directory_path = resolve_path(ctx, directory).path.resolve()
    target_files = _extract_paths(patch, strip, directory_path)

    # dry run first: never touch files unless every hunk can be applied
    dry = _run_patch(directory_path, patch, reverse, strip, fuzz=False, dry_run=True)
    if dry.returncode == 0:
        fuzz = False
    else:
        strict_output = _combined_output(dry)
        dry = _run_patch(directory_path, patch, reverse, strip, fuzz=True, dry_run=True)
        if dry.returncode != 0:
            raise RuntimeError(
                "Patch application failed. The files were not modified.\n"
                f"{strict_output}\n"
                f"{_failure_hint()}"
            )
        fuzz = True

    result = _run_patch(directory_path, patch, reverse, strip, fuzz=fuzz, dry_run=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Patch application failed.\n"
            f"{_combined_output(result)}\n"
            f"{_failure_hint()}"
        )

    output = _combined_output(result)
    message = f"Applied successfully. Modified {len(target_files)} file(s): {', '.join(target_files)}"
    if "fuzz" in output or "offset" in output:
        message += (
            "\nWarning: some hunks were applied with fuzz/offset, "
            "the changes may not be at the intended location. Verify the result."
        )
    return message


def apply_patch_from_files(
    ctx: ToolCallContext,
    source_path: str,
    target_path: str | None = None,
    target_content: str | None = None,
    strip: int = 1,
    directory: str = ".",
) -> str:
    """Apply changes by comparing source and target files."""
    source_path_obj = resolve_path(ctx, source_path).path.resolve()
    directory_path = resolve_path(ctx, directory).path.resolve()

    if not source_path_obj.exists():
        raise FileNotFoundError(f"Source file not found: {source_path_obj}")

    if target_path is None:
        raise ValueError("target_path must be specified")

    target_path_obj = resolve_path(ctx, target_path).path.resolve()
    try:
        rel_path = target_path_obj.relative_to(directory_path)
    except ValueError:
        raise ValueError(
            f"Target file {target_path_obj} is outside the patch directory {directory_path}."
        )

    source_content = source_path_obj.read_text()
    if target_content is None:
        if target_path_obj.exists():
            target_content = target_path_obj.read_text()
        else:
            target_content = ""

    # Generate patch with proper relative paths
    old_path = f"a/{rel_path}"
    new_path = f"b/{rel_path}"
    patch = _generate_patch(source_content, target_content, old_path, new_path)
    if not patch:
        return "No changes to apply."

    return apply_patch(ctx, patch, strip=strip, directory=str(directory_path))


def expose_patch_tools() -> list[Callable]:
    return [apply_patch, apply_patch_from_files]