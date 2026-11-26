"""
repair_report_titles.py

Repair report titles that carry raw markdown.

Problem
-------
When the synthesis LLM opened with a section label written at the
wrong level -- ``### Bottom line`` instead of a ``# `` title -- the
H1 fallback derived the title from the *whole* opening, heading
included. The stored body ended up with a title like::

    # ### Bottom line Among the supplied studies, **plasma N-terminal tau fragment 1**

Both consumers take the first ``# `` line as the title (the PDF
generator and the React UI), so the reader saw the raw markdown.

The derivation is fixed in
``app/infrastructure/llm/title_fallback.py`` (leading headings are
skipped, inline markdown is stripped). This script repairs the
reports that were already written before the fix.

What it does
------------
For every workspace whose stored title carries markdown syntax:

1. Recompute the title from the body *without* the injected H1,
   using the fixed derivation.
2. Rewrite ``summary.body`` and ``report.summary.body``.
3. Re-render the published PDF, so the download matches the page.

The rewrite goes through the domain entities and the repository, so
the ADR-019 corpus invariants are re-validated on the way through.

Usage
-----
Dry run (the default) -- shows what would change::

    PYTHONPATH=. .venv/bin/python scripts/repair_report_titles.py

Apply::

    PYTHONPATH=. .venv/bin/python scripts/repair_report_titles.py --apply

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.domain.entities.published_report import PublishedReport  # noqa: E402
from app.domain.entities.research_report import ResearchReport  # noqa: E402
from app.domain.entities.summary import Summary  # noqa: E402
from app.infrastructure.llm.title_fallback import (  # noqa: E402
    inject_h1_fallback,
)
from app.infrastructure.pdf.reportlab_generator import (  # noqa: E402
    ReportLabPDFGenerator,
    _strip_first_sentence_duplicate,
)
from app.infrastructure.storage.sqlite_workspace_repository import (  # noqa: E402
    SqliteWorkspaceRepository,
)

#: Characters that must never appear in a rendered title.
_MARKDOWN_IN_TITLE = ("#", "**", "`")


def _stored_title(body: str) -> str:
    """Return the title both consumers read: the first ``# `` line."""
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _title_is_broken(body: str) -> bool:
    """Return True when the stored title carries raw markdown."""
    title = _stored_title(body)
    if not title:
        return False
    return any(marker in title for marker in _MARKDOWN_IN_TITLE)


def _body_repeats_the_title(body: str) -> bool:
    """
    Return True when the body's opening prose repeats the title.

    The H1 fallback derives the title from the body's first
    sentence, so the sentence appears twice: once as the title and
    once as the opening paragraph. The PDF generator strips that
    duplicate; a stored PDF rendered before the strip worked has to
    be re-rendered.

    The check asks the generator's own function rather than
    re-implementing the comparison, so the two can never disagree
    about what counts as a duplicate.
    """
    title = _stored_title(body)
    if not title:
        return False
    return _strip_first_sentence_duplicate(body, title) != body


def _repaired_body(body: str) -> str:
    """
    Recompute the body with a clean title.

    The broken title is always the injected H1 -- the first line --
    so the original body is what follows it. Re-running the fixed
    fallback over that original reproduces exactly what a freshly
    generated report would have stored.
    """
    lines = body.split("\n")
    if not lines or not lines[0].startswith("# "):
        return body
    original = "\n".join(lines[1:]).strip()
    if not original:
        return body
    return inject_h1_fallback(original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "bioresearch.db"),
        help="path to the SQLite workspace database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default: dry run)",
    )
    parser.add_argument(
        "--rerender",
        action="store_true",
        help=(
            "also re-render the published PDF of any workspace whose "
            "body repeats the title (the PDF was rendered before the "
            "duplicate-stripping worked)"
        ),
    )
    args = parser.parse_args()

    repository = SqliteWorkspaceRepository(args.db)
    pdf_generator = ReportLabPDFGenerator()

    # Read the ids directly rather than through ``list_workspaces``:
    # a few legacy smoke-test rows carry a non-UUID id ("smoke-test-0")
    # and the repository's deserialiser rejects them. Those rows hold
    # no real report, so skipping them is correct.
    raw_ids = [
        row[0]
        for row in sqlite3.connect(args.db).execute(
            "SELECT id FROM workspaces"
        )
    ]
    workspace_ids: list[UUID] = []
    for raw in raw_ids:
        try:
            workspace_ids.append(UUID(raw))
        except ValueError:
            continue

    fixed_count = 0
    for workspace_id in workspace_ids:
        session = repository.get(workspace_id)
        summary = session.summary
        if summary is None or not summary.body:
            continue
        if not _title_is_broken(summary.body):
            continue

        repaired = _repaired_body(summary.body)
        old_title = _stored_title(summary.body)
        new_title = _stored_title(repaired)
        if old_title == new_title:
            continue

        print(f"{session.id}")
        print(f"  current title : {old_title!r}")
        print(f"  repaired title: {new_title!r}")

        if not args.apply:
            print("  (dry run -- pass --apply to write)")
            fixed_count += 1
            continue

        # 1. The summary.
        new_summary = Summary(
            body=repaired,
            papers_used=list(summary.papers_used or []),
        )
        session.set_summary(new_summary)

        # 2. The report carries its own copy of the summary.
        report = session.report
        if report is not None:
            new_report = ResearchReport(
                summary=new_summary,
                citations=list(report.citations),
                limitations=list(report.limitations),
                future_work=list(report.future_work),
                metadata=dict(report.metadata),
            )
            session.set_report(new_report)

            # 3. Re-render the PDF so the download matches the page.
            if session.published_report is not None:
                pdf_bytes = pdf_generator.generate(new_report)
                session.set_published_report(
                    PublishedReport.create(
                        pdf_bytes=pdf_bytes,
                        workspace_id=str(session.id),
                    )
                )
                print("  re-rendered the published PDF")

        repository.update(session)
        print("  written")
        fixed_count += 1

    if args.rerender:
        print()
        print("Re-rendering PDFs whose body repeats the title:")
        for workspace_id in workspace_ids:
            session = repository.get(workspace_id)
            report = session.report
            if report is None or session.published_report is None:
                continue
            if not _body_repeats_the_title(report.summary.body):
                continue
            pdf_bytes = pdf_generator.generate(report)
            session.set_published_report(
                PublishedReport.create(
                    pdf_bytes=pdf_bytes,
                    workspace_id=str(session.id),
                )
            )
            if args.apply:
                repository.update(session)
                print(f"  {workspace_id}  re-rendered")
            else:
                print(f"  {workspace_id}  would be re-rendered")

    print()
    if fixed_count == 0:
        print("Nothing to repair.")
    elif args.apply:
        print(f"Repaired {fixed_count} report title(s).")
    else:
        print(f"{fixed_count} report title(s) would be repaired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
