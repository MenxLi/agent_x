from typing import Optional, Callable
import subprocess
from ..toolcall import ToolCallContext


def _git(ctx: ToolCallContext, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the agent's workdir."""
    result = subprocess.run(
        ["git", *args],
        cwd=ctx.agent.workdir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "Unknown error"
        raise RuntimeError(f"git {' '.join(args)} failed (exit {result.returncode}): {stderr}")
    return result


def git_status(ctx: ToolCallContext, path: Optional[str] = None) -> str:
    """
    Wrap of `git status --porcelain --branch`.

    Show the working tree status of the git repository.

    Displays branch info, staged changes, unstaged changes, and untracked files.
    Optionally filter to a specific file or path.
    """
    args = ["status", "--porcelain", "--branch", "-unormal"]
    if path:
        args.extend(["--", path])
    result = _git(ctx, *args)
    raw = result.stdout.strip()
    if not raw:
        return "Clean working tree."

    lines = raw.splitlines()
    branch = ""
    staged, unstaged, untracked = [], [], []

    for line in lines:
        if line.startswith("## "):
            branch = line[3:].strip()
        elif line.startswith("?? "):
            untracked.append(line[3:].strip())
        elif line[0] in "ADMRCUX":
            staged.append(line.strip())
        elif line[1] in "MD":
            unstaged.append(line.strip())

    parts = []
    if branch:
        parts.append(f"Branch: {branch}")
    if staged:
        parts.append("\nStaged:")
        parts.extend(f"  {s}" for s in staged)
    if unstaged:
        parts.append("\nUnstaged:")
        parts.extend(f"  {u}" for u in unstaged)
    if untracked:
        parts.append("\nUntracked:")
        parts.extend(f"  {u}" for u in untracked)

    return "\n".join(parts)


def git_diff(ctx: ToolCallContext, path: Optional[str] = None, staged: bool = False) -> str:
    """
    Wrap of `git diff` or `git diff --cached`.

    Show differences between the working tree, index, and HEAD.

    Args:
        path: Optional file or path to limit the diff.
        staged: If True, show staged changes (index vs HEAD). Otherwise show unstaged (working tree vs index).
    """
    stat_args = ["diff", "--stat"]
    if staged:
        stat_args.insert(1, "--cached")
    if path:
        stat_args.extend(["--", path])
    stat_result = _git(ctx, *stat_args)

    diff_args = ["diff", "--unified=3"]
    if staged:
        diff_args.insert(1, "--cached")
    if path:
        diff_args.extend(["--", path])
    diff_result = _git(ctx, *diff_args)

    diff_text = diff_result.stdout.strip()
    if not diff_text:
        return "(no changes)"
    stat_text = stat_result.stdout.strip()
    return f"--- Stats ---\n{stat_text}\n\n--- Diff ---\n{diff_text}"


def git_log(ctx: ToolCallContext, count: int = 10, path: Optional[str] = None) -> str:
    """
    Wrap of `git log`.

    Show commit logs of the git repository.

    Args:
        count: Number of commits to show (default 10).
        path: Optional file or path to show only commits that touched it.
    """
    fmt = "%h %s%nAuthor: %an <%ae>%nDate: %ad%n%n%b%n---%n"
    args = ["log", f"-{count}", f"--format={fmt}", "--date=short", "--decorate"]
    if path:
        args.extend(["--", path])
    result = _git(ctx, *args)
    return result.stdout.rstrip()


def git_show(ctx: ToolCallContext, revision: str = "HEAD") -> str:
    """
    Wrap of `git show`.

    Show the details of a specific commit.

    Args:
        revision: Commit hash, branch name, tag, or ref (default: HEAD).
    """
    fmt = "%h %s%nAuthor: %an <%ae>%nDate: %ad%n%n%b%n---%n"
    args = ["show", f"--format={fmt}", "--date=short", revision]
    result = _git(ctx, *args)
    return result.stdout.rstrip()


def git_branch(ctx: ToolCallContext, remote: bool = False) -> str:
    """
    Wrap of `git branch -v` or `git branch -r -v`.

    List git branches.

    Args:
        remote: If True, list remote-tracking branches. Otherwise list local branches.
    """
    args = ["branch", "-v", "--no-color", "--sort=-committerdate"]
    if remote:
        args.insert(1, "-r")
    result = _git(ctx, *args)
    return result.stdout.rstrip()


def git_blame(ctx: ToolCallContext, path: str) -> str:
    """
    Wrap of `git blame`.

    Show what revision and author last modified each line of a file.

    Args:
        path: The file path to blame (relative to workdir).
    """
    args = ["blame", "-w", "--date=short", "--", path]
    result = _git(ctx, *args)
    return result.stdout.rstrip()


def expose_git_tools() -> list[Callable]:
    """Expose all git tools."""
    return [
        git_status,
        git_diff,
        git_log,
        git_show,
        git_branch,
        git_blame,
    ]
