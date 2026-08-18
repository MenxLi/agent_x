"""File browsing and transfer API for the web display.

All routes are scoped under ``/api/files/{agent_id}`` and serve files from the
agent's workdir only. Symlinks and path components are resolved and re-checked
against the workdir so that neither traversal nor symlink escapes can reach
files outside the agent's workspace.

This module is decoupled from the web display itself: routes resolve agents
through an ``agent_getter`` callback instead of importing the display, and the
zip packing runs on a thread pool so it never blocks the event loop.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

if TYPE_CHECKING:
    from ..agent import Agent

AgentGetter = Callable[[str], "Agent[Agent.T.Any]"]
"""Resolves an agent identifier to an Agent, raising HTTPException(404) when unknown."""

TEXT_SUFFIXES = {
    ".css", ".csv", ".html", ".js", ".json", ".log", ".md",
    ".py", ".rst", ".sh", ".ts", ".tsx", ".txt", ".vue",
    ".c", ".cpp", ".h", ".hpp", ".asm",
    ".java", ".php", ".pl", ".rb", ".rs", ".go",
    ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".properties",
    ".bib", ".ris", ".tex", ".sty", ".cls", ".dtx", ".ltx",
}

MAX_ARCHIVE_SIZE = 1_073_741_824  # 1 GiB hard cap on the packed archive
CHUNK_SIZE = 1024 * 1024
_SLASH_NAME = re.compile(r"[/\\]")


def resolve_path(agent: "Agent[Agent.T.Any]", relative_path: str, *, follow_symlinks: bool = True) -> Path:
    """Resolve ``relative_path`` against the agent workdir and reject escapes."""
    root = agent.workdir.expanduser().resolve()
    target = Path(os.path.abspath(root / relative_path))
    if target != root and root not in target.parents:
        raise HTTPException(400, "Path escapes the agent workdir")
    if follow_symlinks:
        target = target.resolve()
        if target != root and root not in target.parents:
            raise HTTPException(400, "Path escapes the agent workdir")
    return target


def _slugify(path: str) -> str:
    """Name for the download; the empty path (the workdir root) becomes "workspace"."""
    name = path.strip("/").split("/")[-1] or "workspace"
    name = _SLASH_NAME.sub("_", name).strip()
    return name or "workspace"


def _make_archive(agent: "Agent[Agent.T.Any]", path: str) -> tuple[str, str]:
    """Synchronously pack a file or folder in the workdir into a temp zip.

    Runs on a thread pool (via ``run_in_threadpool``) so large archives do not
    block the event loop. Returns ``(temp_zip_path, download_name)``; the
    caller owns the temp file.
    """
    target = resolve_path(agent, path)
    if not target.exists():
        raise HTTPException(404, "Path not found")
    slug = _slugify(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f"xun-archive-{slug}-", suffix=".zip")
    os.close(fd)
    try:
        total = 0
        with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            if target.is_dir():
                # prefix entries with the folder name so extraction lands in a single directory
                prefix = f"{target.name}/"
                files = sorted(target.rglob("*"), key=lambda file: file.relative_to(target).as_posix())
                files = [file for file in files if file.is_file() and not file.is_symlink()]
                base = target
            else:
                prefix = ""
                files = [target]
                base = target.parent
            for item in files:
                info = zipfile.ZipInfo(prefix + item.relative_to(base).as_posix())
                info.external_attr = (item.stat().st_mode & 0xFFFF) << 16
                archive.writestr(info, item.read_bytes())
                total += item.stat().st_size
                if total > MAX_ARCHIVE_SIZE:
                    raise HTTPException(413, "Folder is too large to archive")
        return tmp_name, f"{slug}.zip"
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def build_file_router(agent_getter: AgentGetter) -> APIRouter:
    """Build the file API router.

    ``agent_getter`` maps an agent id (from the URL path) to an Agent and is
    the only hook this module needs on the host application.
    """
    router = APIRouter()

    @router.get("/api/files/{agent_id}")
    async def list_files(agent_id: str, path: str = "") -> dict:
        agent = agent_getter(agent_id)
        target = resolve_path(agent, path)
        if not target.is_dir():
            raise HTTPException(404, "Directory not found")
        entries = []
        for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            stat = item.stat()
            entries.append({
                "name": item.name,
                "path": item.relative_to(agent.workdir.resolve()).as_posix(),
                "kind": "directory" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
                "viewable": item.is_file() and item.suffix.lower() in TEXT_SUFFIXES,
            })
        return {"path": path, "entries": entries}

    @router.get("/api/files/{agent_id}/view")
    async def view_file(agent_id: str, path: str) -> dict[str, str]:
        target = resolve_path(agent_getter(agent_id), path)
        if not target.is_file():
            raise HTTPException(404, "File not found")
        if target.suffix.lower() not in TEXT_SUFFIXES:
            raise HTTPException(415, "File cannot be previewed")
        if target.stat().st_size > 1_000_000:
            raise HTTPException(413, "File is too large to preview")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "File is not UTF-8 text") from exc
        return {"path": path, "content": content}

    @router.get("/api/files/{agent_id}/download")
    async def download_file(agent_id: str, path: str) -> FileResponse:
        target = resolve_path(agent_getter(agent_id), path)
        if not target.is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(target, filename=target.name)

    @router.get("/api/files/{agent_id}/archive")
    async def download_archive(agent_id: str, path: str = "") -> FileResponse:
        """Pack a file or folder in the workdir into a temporary zip and stream it."""
        agent = agent_getter(agent_id)
        tmp_name, download_name = await run_in_threadpool(_make_archive, agent, path)
        return FileResponse(
            tmp_name,
            media_type="application/zip",
            filename=download_name,
            background=BackgroundTask(Path(tmp_name).unlink, missing_ok=True),
        )

    @router.post("/api/files/{agent_id}/upload")
    async def upload_files(
        agent_id: str,
        path: str = Query(default=""),
        files: list[UploadFile] = File(...),
    ) -> dict[str, list[str]]:
        agent = agent_getter(agent_id)
        directory = resolve_path(agent, path)
        if not directory.is_dir():
            raise HTTPException(404, "Directory not found")
        uploaded = []
        for upload in files:
            name = Path(upload.filename or "").name
            if not name:
                continue
            target = resolve_path(agent, str(Path(path) / name))
            with target.open("wb") as output:
                while chunk := await upload.read(CHUNK_SIZE):
                    output.write(chunk)
            uploaded.append(name)
        return {"uploaded": uploaded}

    @router.delete("/api/files/{agent_id}")
    async def delete_file(agent_id: str, path: str) -> dict[str, bool]:
        agent = agent_getter(agent_id)
        target = resolve_path(agent, path, follow_symlinks=False)
        if target == agent.workdir.resolve():
            raise HTTPException(400, "Cannot delete the workdir")
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir():
            try:
                target.rmdir()
            except OSError as exc:
                raise HTTPException(409, "Directory is not empty") from exc
        else:
            raise HTTPException(404, "Path not found")
        return {"deleted": True}

    return router
