"""Document ingestion for the Co personal assistant (ADR-090).

Parses user-uploaded documents (PDF / Word / Excel / CSV / Parquet) into
normalized markdown + extracted tables at upload time. Agents consume the
cached text from the attachments table — they never re-parse binaries.
"""

from nexus.core.ingest.parsers import ParsedDocument, parse_document

__all__ = ["ParsedDocument", "parse_document"]
