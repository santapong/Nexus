"""User file uploads for the Co personal assistant (ADR-089).

POST /api/uploads accepts a multipart file, stores the bytes on local disk
(plain directory — NOT the git-backed workspace store, whose
clone-per-write cost model is wrong for arbitrary user uploads), parses the
document at upload time (ADR-090), and returns an AttachmentRef the client
passes to POST /api/tasks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import structlog
from litestar import Controller, Request, post
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import ClientException
from litestar.params import Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import resolve_workspace_id
from nexus.core.ingest import parse_document
from nexus.db.models import Attachment, AttachmentParseStatus
from nexus.settings import settings

logger = structlog.get_logger()


class AttachmentRef(BaseModel):
    """Reference to an uploaded attachment, returned to the client."""

    id: str
    filename: str
    mime_type: str
    size_bytes: int
    parse_status: str
    parse_error: str | None = None


def _storage_path_for(workspace_id: str, attachment_id: str) -> Path:
    """Filesystem location for an attachment's raw bytes.

    Files are keyed by server-generated IDs only — the user-supplied
    filename is stored in the DB and never used on disk (path traversal).
    """
    return Path(settings.upload_storage_path) / workspace_id / attachment_id


def _write_bytes_sync(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class UploadController(Controller):
    path = "/uploads"

    # Override the app-wide 1MB body cap for file uploads: max file size
    # plus headroom for multipart framing.
    @post(request_max_body_size=settings.upload_max_bytes + 1_048_576)
    async def upload_file(
        self,
        data: Annotated[UploadFile, Body(media_type=RequestEncodingType.MULTI_PART)],
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> AttachmentRef:
        """Upload a file, parse it, and persist an attachments row."""
        workspace_id = await resolve_workspace_id(request, db_session)

        raw = await data.read()
        if len(raw) == 0:
            raise ClientException(detail="Uploaded file is empty")
        if len(raw) > settings.upload_max_bytes:
            raise ClientException(
                detail=f"File exceeds the {settings.upload_max_bytes // (1024 * 1024)}MB limit",
            )

        filename = data.filename or "upload"
        mime_type = data.content_type or "application/octet-stream"

        attachment = Attachment(
            workspace_id=workspace_id,
            task_id=None,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(raw),
            storage_path="",  # set below once the id exists
            parse_status=AttachmentParseStatus.PENDING.value,
        )
        db_session.add(attachment)
        await db_session.flush()  # assigns the id

        path = _storage_path_for(workspace_id, str(attachment.id))
        attachment.storage_path = str(path)
        await asyncio.to_thread(_write_bytes_sync, path, raw)

        parsed = await parse_document(raw, filename=filename, mime_type=mime_type)
        attachment.parsed_text = parsed.markdown or None
        attachment.parsed_tables = parsed.tables or None
        attachment.parse_status = parsed.status
        attachment.parse_error = parsed.error
        await db_session.commit()

        logger.info(
            "attachment_uploaded",
            attachment_id=str(attachment.id),
            workspace_id=workspace_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(raw),
            parse_status=parsed.status,
        )

        return AttachmentRef(
            id=str(attachment.id),
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(raw),
            parse_status=parsed.status,
            parse_error=parsed.error,
        )
