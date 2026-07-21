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
from functools import lru_cache
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

# Default fixture filenames. Callers can point the client at a different fixture
# set (e.g. the mock-pipeline demo fixtures) via the constructor without touching
# these defaults, which the DI provider and the existing tests rely on.
_DEFAULT_BULLETINS_FIXTURE = "month_bulletins.json"
_DEFAULT_DOCUMENTS_FIXTURE = "documents_by_bopa_77_2026.json"

# A tiny stand-in for a real document's HTML body, returned by ``fetch_content``.
_CANNED_HTML = (
    "<html><head><title>BOPA document (mock)</title></head>"
    "<body><p>Mock BOPA document content.</p></body></html>"
).encode("utf-8")


@lru_cache(maxsize=None)
def _load_bulletins(filename: str) -> list[BopaBulletinListItem]:
    """Load and validate a bulletins fixture, cached so each file is parsed once."""
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return TypeAdapter(list[BopaBulletinListItem]).validate_python(raw)


@lru_cache(maxsize=None)
def _load_documents_page(filename: str) -> BopaDocumentsPage:
    """Load and validate a documents-page fixture, cached so each file is parsed once."""
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return BopaDocumentsPage.model_validate(raw)


# Validate the default fixtures once at import so a malformed default fails loudly
# and early rather than on the first request. These are the exact (cached) objects
# the default constructor serves, since the loaders are memoized per filename.
_MONTH_BULLETINS = _load_bulletins(_DEFAULT_BULLETINS_FIXTURE)
_DOCUMENTS_PAGE = _load_documents_page(_DEFAULT_DOCUMENTS_FIXTURE)


class MockBopaClient(BopaClient):
    """A :class:`BopaClient` backed by committed JSON fixtures.

    ``bulletins_fixture`` / ``documents_fixture`` default to the standard demo
    fixtures; pass different filenames (relative to ``fixtures/``) to serve an
    alternative fixture set, such as the crafted mock-pipeline demo data. The
    chosen fixtures are validated lazily on construction (cached per filename).
    """

    def __init__(
        self,
        *,
        blob_base_url: str = DEFAULT_BLOB_BASE_URL,
        bulletins_fixture: str = _DEFAULT_BULLETINS_FIXTURE,
        documents_fixture: str = _DEFAULT_DOCUMENTS_FIXTURE,
    ) -> None:
        self._blob_base_url = blob_base_url
        self._bulletins = _load_bulletins(bulletins_fixture)
        self._documents_page = _load_documents_page(documents_fixture)

    def get_month_bulletins(
        self, reference_date: date
    ) -> list[BopaBulletinListItem]:
        """Return the fixture issues (``reference_date`` is ignored by the mock)."""
        return list(self._bulletins)

    def get_documents_by_bopa(self, year: int, num: int) -> BopaDocumentsPage:
        """Return the fixture documents page (``year``/``num`` ignored by the mock)."""
        return self._documents_page.model_copy(deep=True)

    def build_pdf_url(self, year: int, num: int, document_name: str) -> str:
        return build_pdf_url(self._blob_base_url, year, num, document_name)

    def build_sumari_pdf_url(self, year: int, num: int) -> str:
        return build_sumari_pdf_url(self._blob_base_url, year, num)

    def fetch_content(self, source_url: str) -> bytes:
        return _CANNED_HTML
