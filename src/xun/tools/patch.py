from pathlib import Path
import re
from typing import Callable
import subprocess
from .fs import resolve_path
from ..toolcall import ToolCallContext


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _normalize_patch(patch: str) -> str:
    """Ensure a patch stream ends with a newline, as required by patch tools."""
    return patch if patch.endswith("\n") else f"{patch}\n"


def _enhance_patch_error(stderr: str) -> str:
    """Add helpful hints to common patch errors."""
    enhanced = stderr
    if "corrupt patch" in stderr:
        hint = "\nTip: This error often occurs when the line counts in the hunk header (@@ -start,count +start,count @@) don't match the actual file content. Verify that the counts in your patch correspond to the actual number of lines being modified."
        enhanced += hint
    return enhanced


def _patch_paths(patch: str) -> list[str]:
    """Extract old and new paths from unified-diff file headers."""
    paths = []
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")):
            path = line[4:].split("\t", 1)[0]
            if path != "/dev/null":
                paths.append(path)
    return paths


def _strip_path(path: str, strip: int) -> str:
    if strip < 0:
        raise ValueError("strip must not be negative.")

    parts = path.split("/")
    if len(parts) <= strip:
        raise ValueError(f"Path '{path}' has fewer than {strip} leading component(s) to strip.")
    return "/".join(parts[strip:])


def _validate_patch_paths(patch: str, strip: int, directory: Path) -> list[str]:
    """Ensure every relative patch path stays inside the selected directory."""
    target_paths = []
    for path in _patch_paths(patch):
        target_path = _strip_path(path, strip)
        if Path(target_path).is_absolute():
            raise ValueError(f"Patch path '{path}' must be relative to the patch directory.")
        resolved = (directory / target_path).resolve()
        if not resolved.is_relative_to(directory):
            raise ValueError(
                f"Patch path '{path}' escapes the patch directory '{directory}'."
            )
        if target_path not in target_paths:
            target_paths.append(target_path)
    return target_paths


def _validate_patch(patch: str) -> None:
    """Validate that the patch looks like a proper unified diff."""
    if not patch.strip():
        raise ValueError("Patch content is empty.")
    has_file_header = "--- " in patch and "+++" in patch
    has_hunk_marker = "@@" in patch
    if not (has_file_header and has_hunk_marker):
        missing = []
        if not has_file_header:
            missing.append("'--- ' / '+++ ' file headers")
        if not has_hunk_marker:
            missing.append("'@@' hunk markers")
        raise ValueError(
            f"Not a valid unified diff. Missing: {', '.join(missing)}. "
            "See git diff output format for reference."
        )

    _validate_hunk_headers(patch)


def _validate_hunk_headers(patch: str) -> None:
    """Validate that hunk headers have correct @@ format.
    Skips strict line count checking — that's handled by git apply / patch.
    """
    for i, line in enumerate(patch.splitlines(), 1):
        if line.startswith("@@"):
            match = _HUNK_HEADER.match(line)
            if match is None:
                raise ValueError(f"Invalid hunk header at patch line {i}: {line!r}")


def _is_git_repo(path: str) -> bool:
    """Check if a directory is a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def apply_patch(
    ctx: ToolCallContext,
    patch: str,
    reverse: bool = False,
    strip: int = 1,
    directory: str = ".",
) -> str:
    """
    Wrap of `git apply` (or `patch`). Apply a unified diff patch to the file(s)
    Works in git and non-git repos. Uses `git apply` when possible, otherwise falls back to `patch`.
    Args:
        patch: A unified diff with file headers ('--- a/...', '+++ b/...') and hunk markers ('@@ ... @@').
        reverse: If True, reverse the patch (revert the changes).
        strip: Leading path components to strip (default 1, removes 'a/' and 'b/' prefix).
        directory: Workdir-relative or registered-tempdir path in which to apply the patch (default '.').
    """
    patch = _normalize_patch(patch)
    _validate_patch(patch)
    directory_path = resolve_path(ctx, directory).path.resolve()
    target_files = _validate_patch_paths(patch, strip, directory_path)

    is_git = _is_git_repo(str(directory_path))

    if is_git:
        _apply_with_git(directory_path, patch, reverse, strip)
    else:
        _apply_with_patch_cmd(directory_path, patch, reverse, strip)

    return f"Applied successfully. Modified {len(target_files)} file(s): {', '.join(target_files)}"


def _apply_with_git(directory: Path, patch: str, reverse: bool, strip: int) -> None:
    """Apply a patch using `git apply`."""
    args = ["apply", "--inaccurate-eof", "-p", str(strip)]
    if reverse:
        args.append("--reverse")
    check_result = subprocess.run(
        ["git", *args, "--check"],
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check_result.returncode != 0:
        stderr = check_result.stderr.strip() or "Check failed"
        raise RuntimeError(f"Patch check failed: {_enhance_patch_error(stderr)}")

    result = subprocess.run(
        ["git", *args],
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "Apply failed"
        raise RuntimeError(f"Patch application failed:\n{_enhance_patch_error(stderr)}")


def _apply_with_patch_cmd(directory: Path, patch: str, reverse: bool, strip: int) -> None:
    """Apply a patch using the `patch` command (non-git fallback)."""
    args = ["-p", str(strip)]
    if reverse:
        args.append("-R")

    check_result = subprocess.run(
        ["patch", "--dry-run", *args],
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check_result.returncode not in (0, 1):
        stderr = check_result.stderr.strip() or check_result.stdout.strip() or "Dry-run failed"
        raise RuntimeError(f"Patch dry-run failed: {_enhance_patch_error(stderr)}")

    result = subprocess.run(
        ["patch", *args],
        cwd=directory,
        input=patch,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode not in (0, 1):
        stderr = result.stderr.strip() or result.stdout.strip() or "Apply failed"
        raise RuntimeError(f"Patch application failed:\n{_enhance_patch_error(stderr)}")


def expose_patch_tools() -> list[Callable]:
    return [apply_patch]