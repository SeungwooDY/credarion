"""File upload handling for invoice images and PDFs."""
from __future__ import annotations

import uuid
from pathlib import Path


def save_upload(content: bytes, file_type: str, upload_dir: str) -> tuple[str, str]:
    """Save uploaded file content to disk.

    Returns:
        (file_id, relative_path) where relative_path is '{file_id}.{ext}'.
    """
    dir_path = Path(upload_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    ext = file_type.lower().lstrip(".")
    relative_path = f"{file_id}.{ext}"
    full_path = dir_path / relative_path

    full_path.write_bytes(content)
    return file_id, relative_path


def get_file_path(file_url: str, upload_dir: str) -> str:
    """Resolve a stored file_url to an absolute path."""
    return str(Path(upload_dir) / file_url)
