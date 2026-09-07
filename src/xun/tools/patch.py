from pathlib import Path
import re
from typing import Callable
import subprocess
from .common import resolve_path
from ..toolcall import ToolCallContext

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")

# how many context lines `patch` may ignore on the relaxed second attempt
_MAX_FUZZ = 2

# git headers that carry no text hunk at all, so patch(1) has nothing to do
_GIT_METADATA_HEADERS = (
    "rename from ", "rename to ", "similarity index ", "old mode ", "new mode ",
    "GIT binary patch", "Binary files ",
)


def _normalize_patch(patch: str) -> str:
    """Ensure patch ends with a newline."""
    return patch if patch.endswith("\n") else f"{patch}\n"


def _combined_output(result: subprocess.CompletedProcess) -> str:
    """patch reports hunk failures on stdout, so always merge both streams."""
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


def _files_without_final_newline(directory: Path, paths: list[str]) -> list[str]:
    """Paths whose last line is not terminated by a newline."""
    without = []
    for rel in paths:
        try:
            file = directory / rel
            if file.is_file() and not file.read_bytes().endswith(b"\n"):
                without.append(rel)
        except OSError:
            continue
    return without


def _failure_hint(patch: str, output: str, directory: Path, targets: list[str]) -> str:
    """Advice matching what `patch` actually complained about, '' if we know no more."""
    low = output.lower()
    hints = []
    if "wrong -p" in low or "no file to patch" in low or "can't find file to patch" in low:
        hints.append(
            "The paths do not match after stripping prefixes: keep strip=1 for 'a/'/'b/' "
            "prefixed diffs, pass strip=0 for plain relative paths."
        )
    if "reversed (or previously applied)" in low:
        hints.append(
            "The change is already present in the file, so regenerating the patch will not "
            "help; to undo it call again with reverse=true."
        )
    if "dangerous file name" in low:
        hints.append("Patch paths must stay inside the patch directory: no '..', no absolute path.")
    if "malformed patch" in low or "unexpected end" in low:
        hints.append(
            "Some hunk line counts are wrong: in '@@ -L,C +L,C @@' the first C must equal the "
            "number of '-' plus context lines and the second C the '+' plus context lines."
        )
    if not hints:
        no_newline = _files_without_final_newline(directory, targets)
        if no_newline and "\\ No newline" not in patch:
            hints.append(
                f"These files do not end with a newline: {', '.join(no_newline)}. A hunk that "
                "touches their last line must carry a '\\ No newline at end of file' marker line "
                "after it, otherwise that line never matches."
            )
        else:
            hints.append(
                "Common causes: the target file changed since the patch was created, or the "
                "patch's line numbers/context lines are wrong. Re-read the target file and "
                "regenerate the patch against its current content."
            )
    return "\n".join(hints)


def _run_patch(
    directory: Path,
    patch: str,
    reverse: bool,
    strip: int,
    fuzz: int,
    dry_run: bool,
) -> subprocess.CompletedProcess:
    """Run the `patch` command in non-interactive mode."""
    args = ["patch", "-p", str(strip), "--batch", "--no-backup-if-mismatch", f"--fuzz={fuzz}"]
    if not reverse:
        # refuse already-applied patches instead of prompting to reverse them
        args.append("--forward")
    if dry_run:
        args.append("--dry-run")
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
        if not has_file_header and ("diff --git" in patch or any(h in patch for h in _GIT_METADATA_HEADERS)):
            raise ValueError(
                "This diff only carries git metadata (rename, mode change or binary content), "
                "which patch(1) cannot apply. Use `git apply`, or rename/delete/create with the "
                "file tools."
            )
        if has_file_header and not has_hunk:
            raise ValueError(
                "This diff has no '@@' hunk, so there is nothing to change (an empty new file or "
                "a mode-only change). Use the file tools instead."
            )
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


def _decoded_path(raw: str) -> str:
    """Undo git's C-style quoting of a file name.

    git escapes the raw *bytes* of the name, so '"a/caf\\303\\251.txt"' holds the
    UTF-8 bytes of 'a/cafe.txt'; a name git leaves alone is already plain UTF-8.
    """
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    name = bytearray()
    at = 0
    while at < len(raw):
        escaped = _OCTAL_ESCAPE.match(raw, at)
        if escaped:
            name.append(int(escaped.group(1), 8))
            at = escaped.end()
        else:
            name += raw[at].encode("utf-8", "surrogateescape")
            at += 1
    return name.decode("utf-8", "replace")


def _patch_targets(patch: str, strip: int, directory: Path) -> dict[str, str]:
    """Map every in-directory path the patch touches to 'modify', 'create' or 'delete'."""

    def inside(raw: str) -> str | None:
        if not raw or raw == "/dev/null":
            return None
        parts = _decoded_path(raw).split("/")
        if len(parts) <= strip:
            return None
        rel = "/".join(parts[strip:])
        return rel if (directory / rel).resolve().is_relative_to(directory) else None

    targets: dict[str, str] = {}
    old = ""
    for line in patch.splitlines():
        if line.startswith("--- "):
            old = line[3:].lstrip().split("\t", 1)[0].strip()
            continue
        if not line.startswith("+++ "):
            continue
        new = line[3:].lstrip().split("\t", 1)[0].strip()
        if old == "/dev/null":
            kind, rel = "create", inside(new)
        elif new == "/dev/null":
            kind, rel = "delete", inside(old)
        else:
            kind, rel = "modify", inside(old) or inside(new)
        if rel and rel not in targets:
            targets[rel] = kind
        old = ""
    return targets


def _summarize(targets: dict[str, str]) -> str:
    """One line per kind of change, so a deleted file is not reported as modified."""
    parts = []
    for kind, verb in (("modify", "Modified"), ("create", "Created"), ("delete", "Deleted")):
        paths = sorted(path for path, k in targets.items() if k == kind)
        if paths:
            parts.append(f"{verb} {len(paths)} file(s): {', '.join(paths)}")
    return "; ".join(parts) if parts else "No files touched"


def _extract_paths(patch: str, strip: int, directory: Path) -> list[str]:
    """Extract and validate paths in the patch."""
    return sorted(_patch_targets(patch, strip, directory))


def apply_patch(
    ctx: ToolCallContext,
    patch: str,
    reverse: bool = False,
    strip: int = 1,
    directory: str = ".",
) -> str:
    """Apply a unified diff patch.

    The patch is always dry-run first, so a failing patch never leaves files
    half-modified. The first attempt requires every context line to match; only
    if that fails is a second attempt made allowing small context offsets, and
    the result is then flagged for verification.
    """
    patch = _normalize_patch(patch)
    _validate_patch(patch)

    directory_path = resolve_path(ctx, directory).path.resolve()
    if not directory_path.is_dir():
        raise ValueError(f"Patch directory does not exist: {directory_path}")
    targets = _patch_targets(patch, strip, directory_path)
    names = sorted(targets)

    # dry run first: never touch files unless every hunk can be applied
    dry = _run_patch(directory_path, patch, reverse, strip, fuzz=0, dry_run=True)
    if dry.returncode == 0:
        fuzz = 0
    else:
        strict_output = _combined_output(dry)
        dry = _run_patch(directory_path, patch, reverse, strip, fuzz=_MAX_FUZZ, dry_run=True)
        if dry.returncode != 0:
            raise RuntimeError(
                "Patch application failed. The files were not modified.\n"
                f"{strict_output}\n"
                f"{_failure_hint(patch, strict_output, directory_path, names)}"
            )
        fuzz = _MAX_FUZZ

    result = _run_patch(directory_path, patch, reverse, strip, fuzz=fuzz, dry_run=False)
    if result.returncode != 0:
        output = _combined_output(result)
        raise RuntimeError(
            "Patch application failed.\n"
            f"{output}\n"
            f"{_failure_hint(patch, output, directory_path, names)}"
        )

    output = _combined_output(result)
    message = f"Applied successfully. {_summarize(targets)}"
    if "fuzz" in output or "offset" in output:
        message += (
            "\nWarning: some hunks were applied with fuzz/offset, "
            "the changes may not be at the intended location. Verify the result."
        )
    return message


def expose_patch_tools() -> list[Callable]:
    return [apply_patch]