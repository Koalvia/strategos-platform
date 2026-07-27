"""Fixture-backed BOPA client.

:class:`MockBopaClient` implements the :class:`BopaClient` port by reading
committed JSON fixtures under ``fixtures/``. It performs no network I/O and needs
no credentials, so downstream ingestion features can be built and demoed against a
stable contract before the live client is switched on.

Fixtures are loaded and validated into the transport DTOs once at import time, so
a malformed fixture fails loudly and early rather than on the first request. The
URL builders are pure string construction (no fixture needed); ``fetch_content``
returns a small canned HTML body.
"""

import json
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from app.integrations.bopa.client import (
    DEFAULT_BLOB_BASE_URL,
    BopaClient,
    build_pdf_url,
    build_sumari_pdf_url,
)
from app.integrations.bopa.models import (
    BopaBulletinListItem,
    BopaDocumentsPage,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Committed real HTML bodies, keyed by their file name. A document whose
# ``source_url`` ends with one of these names is served its genuine body (so the
# analysis pipeline reads the real edict text and can match it against
# customers); every other document falls back to the canned stub below.
_BODIES_DIR = _FIXTURES_DIR / "bodies"

# A tiny stand-in for a real document's HTML body, returned by ``fetch_content``
# for any document without a committed body.
_CANNED_HTML = (
    "<html><head><title>BOPA document (mock)</title></head>"
    "<body><p>Mock BOPA document content.</p></body></html>"
).encode("utf-8")


def _load_bulletins(filename: str) -> list[BopaBulletinListItem]:
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return TypeAdapter(list[BopaBulletinListItem]).validate_python(raw)


def _load_documents_page(filename: str) -> BopaDocumentsPage:
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return BopaDocumentsPage.model_validate(raw)


def _load_bodies() -> dict[str, bytes]:
    """Read every ``bodies/*.html`` fixture into a ``{file_name: bytes}`` map."""
    if not _BODIES_DIR.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in _BODIES_DIR.glob("*.html")}


# Validate every fixture once at import.
_MONTH_BULLETINS = _load_bulletins("month_bulletins.json")
_DOCUMENTS_PAGE = _load_documents_page("documents_by_bopa_82_2026.json")
_BODIES = _load_bodies()


class MockBopaClient(BopaClient):
    """A :class:`BopaClient` backed by committed JSON fixtures."""

    def __init__(self, *, blob_base_url: str = DEFAULT_BLOB_BASE_URL) -> None:
        self._blob_base_url = blob_base_url

    def get_month_bulletins(
        self, reference_date: date
    ) -> list[BopaBulletinListItem]:
        """Return the fixture issues (``reference_date`` is ignored by the mock)."""
        return list(_MONTH_BULLETINS)

    def get_documents_by_bopa(self, year: int, num: int) -> BopaDocumentsPage:
        """Return the fixture documents page (``year``/``num`` ignored by the mock)."""
        return _DOCUMENTS_PAGE.model_copy(deep=True)

    def build_pdf_url(self, year: int, num: int, document_name: str) -> str:
        return build_pdf_url(self._blob_base_url, year, num, document_name)

    def build_sumari_pdf_url(self, year: int, num: int) -> str:
        return build_sumari_pdf_url(self._blob_base_url, year, num)

    def fetch_content(self, source_url: str) -> bytes:
        """Return a document's committed real body, or the canned stub.

        ``source_url`` is a blob path ending in the document's file name (e.g.
        ``.../html/GF_2026_07_16_11_16_54.html``); a body committed under
        ``fixtures/bodies/`` with that name is returned so the pipeline sees the
        genuine edict text. Anything else falls back to ``_CANNED_HTML``.
        """
        file_name = source_url.rsplit("/", 1)[-1]
        return _BODIES.get(file_name, _CANNED_HTML)
