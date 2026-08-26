"""
published_report.py

Domain entity representing the PDF export of a final research
report.

A ``PublishedReport`` is the durable artefact produced by the
``PUBLISH`` action. It wraps the underlying ``ResearchReport``
(whose content stays unchanged) plus the rendered PDF bytes and
the metadata needed to serve the download later.

This entity lives in the Domain layer because it's a value
object -- the PDF bytes are immutable and the entity doesn't know
how the bytes were generated. The actual PDF generation lives in
the infrastructure layer (``app.infrastructure.pdf.generator``).

Why a separate entity (vs. just storing the PDF bytes on the
session)
----------------------------------------------------------------------
We *could* have made ``ResearchSession.published_pdf`` a plain
``bytes`` field. The reasons we use a proper dataclass:

  - **Type safety**: ``published_pdf: bytes`` is too loose -- a
    caller could assign arbitrary bytes (e.g. a text snippet
    accidentally). The dataclass enforces the structure.
  - **Validation**: ``__post_init__`` checks the PDF magic bytes
    (``%PDF-``) and size limits. Storing a corrupted or truncated
    blob becomes a hard failure, not a silent render-bug later.
  - **Audit-trail metadata**: ``created_at`` and ``byte_size``
    are useful for the GET endpoint (Content-Length, Last-Modified)
    and for debugging "why is this PDF 50MB?".

Lifecycle
---------
A ``PublishedReport`` is created by the orchestrator's
``publish_report()`` method (the ``PUBLISH`` action) and persisted
alongside the session. Subsequent ``PUBLISH`` calls overwrite the
old artefact (publishing always regenerates the PDF from the
latest report content -- the user might have re-run REPORT to
incorporate a new paper, and the old PDF would be stale).

The ``Workspace`` FSM holds one ``PublishedReport`` at most.
A re-publish replaces it.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC


# Minimum sensible size for a valid PDF: a one-page document with
# just a hello-world text is around 400 bytes. Anything smaller is
# almost certainly truncated or empty.
_MIN_PDF_BYTES: int = 200

# Reject obviously-too-large PDFs at the entity boundary too. The
# PDF_UPLOAD_MAX_BYTES env var caps incoming uploads at 200 MB; we
# apply a tighter cap here for *outgoing* PDFs (the rendered report
# rarely needs more than a few MB unless the user has thousands of
# citations).
_MAX_PDF_BYTES: int = 50 * 1024 * 1024  # 50 MB


@dataclass(slots=True)
class PublishedReport:
    """
    A rendered PDF of a research report, ready for download.

    Attributes
    ----------
    pdf_bytes : bytes
        The raw PDF file contents. Must start with the PDF magic
        header (``b"%PDF-"``) per the PDF 1.7 spec.

    created_at : datetime
        UTC timestamp recording when the PDF was generated.
        Useful for ``Last-Modified`` headers and for debugging
        stale-PDF reports.

    byte_size : int
        Length of ``pdf_bytes`` in bytes. Cached here so the
        download endpoint can set ``Content-Length`` without
        re-measuring the bytes every request.

    workspace_id : str
        ID of the workspace that produced this PDF. Stored for
        log/audit traceability -- the PDF is served by ID, not by
        embedded ID, so we don't need to verify, but having the
        pointer in the blob metadata makes audits straightforward.

    Notes
    -----
    ``slots=True`` saves memory when many workspaces accumulate
    PDFs over time (Redis cache layer caches these).
    """

    pdf_bytes: bytes
    created_at: datetime
    byte_size: int
    workspace_id: str

    def __post_init__(self) -> None:
        # PDF magic header: every valid PDF begins with ``%PDF-``.
        # This is the only reliable content-sniffing signal we have
        # for the format; everything else can be compressed/encrypted.
        if not self.pdf_bytes.startswith(b"%PDF-"):
            raise ValueError(
                "PublishedReport.pdf_bytes does not start with "
                "the PDF magic header (b'%PDF-'). Got "
                f"{self.pdf_bytes[:8]!r}."
            )
        if self.byte_size != len(self.pdf_bytes):
            raise ValueError(
                "PublishedReport.byte_size does not match the "
                f"actual length of pdf_bytes "
                f"(declared {self.byte_size}, actual "
                f"{len(self.pdf_bytes)})."
            )
        if self.byte_size < _MIN_PDF_BYTES:
            raise ValueError(
                f"PublishedReport.pdf_bytes is too small "
                f"({self.byte_size} bytes; minimum is "
                f"{_MIN_PDF_BYTES}). The PDF is likely truncated."
            )
        if self.byte_size > _MAX_PDF_BYTES:
            raise ValueError(
                f"PublishedReport.pdf_bytes is too large "
                f"({self.byte_size} bytes; maximum is "
                f"{_MAX_PDF_BYTES})."
            )

    @classmethod
    def create(cls, pdf_bytes: bytes, workspace_id: str) -> "PublishedReport":
        """Factory that stamps ``created_at`` and ``byte_size``.

        Direct construction is awkward because the caller has to
        pass a ``created_at`` and ``byte_size`` that agree with
        ``pdf_bytes``. The validator in ``__post_init__`` enforces
        that, but ``create`` is the ergonomic entry point.
        """
        return cls(
            pdf_bytes=pdf_bytes,
            created_at=datetime.now(UTC),
            byte_size=len(pdf_bytes),
            workspace_id=workspace_id,
        )

    def __repr__(self) -> str:
        # Bytes-typed fields dominate __repr__'s output by default;
        # keep the repr terse so logs and error messages stay readable.
        return (
            f"PublishedReport(workspace_id={self.workspace_id!r}, "
            f"byte_size={self.byte_size}, "
            f"created_at={self.created_at.isoformat()})"
        )
