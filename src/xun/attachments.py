from __future__ import annotations

import re
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_ATTACHMENT_ID = re.compile(r"^[0-9a-f]{32}\.(gif|jpe?g|png|webp)$")
_FORMAT_SUFFIX = {
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class AttachmentError(ValueError):
    pass


class AttachmentStore:
    """Persist validated image attachments behind opaque identifiers."""

    def __init__(self, directory: Path, max_bytes: int = MAX_ATTACHMENT_BYTES) -> None:
        self.directory = directory.expanduser().resolve()
        self.max_bytes = max_bytes

    def save_image(self, data: bytes) -> str:
        if not data:
            raise AttachmentError("Image is empty")
        if len(data) > self.max_bytes:
            raise AttachmentError(f"Image exceeds the {self.max_bytes // (1024 * 1024)} MB limit")

        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
                suffix = _FORMAT_SUFFIX.get(image.format or "")
        except (UnidentifiedImageError, OSError) as exc:
            raise AttachmentError("File is not a supported image") from exc

        if suffix is None:
            raise AttachmentError("Supported image formats are PNG, JPEG, WebP, and GIF")

        self.directory.mkdir(parents=True, exist_ok=True)
        attachment_id = f"{uuid.uuid4().hex}{suffix}"
        (self.directory / attachment_id).write_bytes(data)
        return attachment_id

    def resolve(self, attachment_id: str) -> Path:
        if not _ATTACHMENT_ID.fullmatch(attachment_id):
            raise AttachmentError("Invalid attachment ID")
        path = (self.directory / attachment_id).resolve()
        if self.directory not in path.parents:
            raise AttachmentError("Attachment escapes the storage directory")
        if not path.is_file():
            raise AttachmentError("Attachment not found")
        return path
