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


def _enhance_patch_error(stderr: str) -> str:
    """Enhanced error message for patch failures."""
    enhanced = stderr
    if "corrupt" in stderr.lower():
        hint = "\nTip: Use `apply_patch_from_files` if you have original/modified files, or ensure the target file hasn't changed since patch creation."
        enhanced += hint
    return enhanced


def _apply_patch_cmd(
    directory: Path,
    patch: str,
    reverse: bool,
    strip: int,
    fuzz: bool = False,
) -> None:
    """Apply patch using the `patch` command."""
    args = ["-p", str(strip), "--no-backup-if-mismatch"]
    if fuzz:
        args.append("--fuzz=5")
    if reverse:
        args.append("-R")

    result = subprocess.run(
        ["patch", *args],
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip() or "Patch failed"
        raise RuntimeError(f"Patch application failed: {_enhance_patch_error(stderr)}")


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


def _is_git_repo(path: str) -> bool:
    """Check if directory is a git repository."""
    return subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,
    ).returncode == 0


def _generate_patch(from_content: str, to_content: str, old_path: str, new_path: str) -> str:
    """Generate a unified diff patch."""
    from_lines = from_content.splitlines(keepends=True)
    to_lines = to_content.splitlines(keepends=True)

    diff = unified_diff(from_lines, to_lines, fromfile=old_path, tofile=new_path, lineterm="")
    patch = "\n".join(diff)
    return patch + "\n" if patch else ""


def _extract_paths(patch: str, strip: int, directory: Path) -> list[str]:
    """Extract and validate paths in the patch."""
    paths = set()
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")) and line.strip() != "/dev/null":
            path = line[4:].split("\t", 1)[0]
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            if path:
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
    """Apply a unified diff patch with fuzzy fallback."""
    patch = _normalize_patch(patch)
    _validate_patch(patch)

    directory_path = resolve_path(ctx, directory).path.resolve()
    target_files = _extract_paths(patch, strip, directory_path)

    is_git = _is_git_repo(str(directory_path))

    # Try git apply first in git repo, fall back to patch with fuzz
    if is_git:
        try:
            _apply_patch_cmd(
                directory_path,
                patch,
                reverse,
                strip,
                fuzz=False,
            )
        except RuntimeError:
            _apply_patch_cmd(
                directory_path,
                patch,
                reverse,
                strip,
                fuzz=True,
            )
    else:
        _apply_patch_cmd(
            directory_path,
            patch,
            reverse,
            strip,
            fuzz=True,
        )

    return f"Applied successfully. Modified {len(target_files)} file(s): {', '.join(target_files)}"


def apply_patch_from_files(
    ctx: ToolCallContext,
    source_path: str,
    target_path: str | None = None,
    target_content: str | None = None,
    strip: int = 1,
    directory: str = ".",
) -> str:
    """Apply changes by comparing source and target files."""
    source_path_obj = resolve_path(ctx, source_path).path
    directory_path = resolve_path(ctx, directory).path.resolve()

    if not source_path_obj.exists():
        raise FileNotFoundError(f"Source file not found: {source_path_obj}")

    source_content = source_path_obj.read_text()

    if target_path is None:
        raise ValueError("target_path must be specified")

    target_path_obj = resolve_path(ctx, target_path).path
    if target_content is None:
        if target_path_obj.exists():
            target_content = target_path_obj.read_text()
        else:
            target_content = ""

    # Generate patch with proper relative paths
    rel_path = target_path_obj.relative_to(directory_path)
    old_path = f"a/{rel_path}"
    new_path = f"b/{rel_path}"
    patch = _generate_patch(source_content, target_content, old_path, new_path)

    return apply_patch(ctx, patch, strip=strip, directory=str(directory_path))


def expose_patch_tools() -> list[Callable]:
    return [apply_patch, apply_patch_from_files]