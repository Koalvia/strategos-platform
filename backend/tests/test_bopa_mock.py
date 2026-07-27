"""Tests for the BOPA integration port, mock client and DI switch (issue #48).

These cover the seam: a fixture-backed ``MockBopaClient`` implementing the
``BopaClient`` port, the pure blob-URL builders shared with the live client, and
the ``get_bopa_client`` provider gated on ``settings.BOPA_MODE``. No network or
credentials are involved.
"""

from datetime import date, datetime, timezone

import pytest

from app.core.config import settings
from app.core.dependencies import get_bopa_client
from app.integrations.bopa import (
    BopaClient,
    LiveBopaClient,
    MockBopaClient,
)
from app.integrations.bopa.client import pad3
from app.integrations.bopa.models import (
    BopaBulletinListItem,
    BopaDocument,
    BopaDocumentsPage,
)


@pytest.fixture
def client() -> MockBopaClient:
    return MockBopaClient()


@pytest.mark.unit
def test_mock_implements_port(client):
    """The mock is an instance of the abstract port."""
    assert isinstance(client, BopaClient)


@pytest.mark.unit
def test_mock_validates_fixtures_at_import():
    """Importing the mock module validates its fixtures without error."""
    # Re-importing is a no-op, but the module-level validation already ran at
    # first import; assert the loaded fixtures have the expected shapes.
    from app.integrations.bopa import mock_client

    assert all(
        isinstance(b, BopaBulletinListItem) for b in mock_client._MONTH_BULLETINS
    )
    assert isinstance(mock_client._DOCUMENTS_PAGE, BopaDocumentsPage)


@pytest.mark.unit
def test_get_month_bulletins_parses_fixture(client):
    """The listing fixture validates into DTOs with the year parsed out."""
    items = client.get_month_bulletins(date(2026, 7, 1))
    assert len(items) == 1

    first = items[0]
    assert first.num == 82
    assert first.year == 2026
    assert first.is_extra is False
    assert first.published_at == datetime(2026, 7, 21, 22, 0, tzinfo=timezone.utc)


@pytest.mark.unit
def test_get_documents_by_bopa_parses_fixture(client):
    """The documents fixture unwraps paginatedDocuments and maps every field."""
    page = client.get_documents_by_bopa(2026, 82)
    assert isinstance(page, BopaDocumentsPage)
    # The API's totalCount exceeds the documents actually returned (a known
    # upstream quirk); the fixture preserves it.
    assert page.total_count == 209
    assert len(page.documents) == 3

    doc = page.documents[0]
    assert isinstance(doc, BopaDocument)
    assert doc.storage_name == "GF_2026_07_16_11_16_54.html"
    assert doc.storage_size == 1873
    assert doc.source_url.endswith("/038082/html/GF_2026_07_16_11_16_54.html")
    assert doc.organisme == "Notificacions"
    assert doc.organisme_pare == "03. Govern"
    assert doc.tema_pare == "15. Notificacions"
    assert doc.file_type == "html"
    assert doc.num == 82
    assert doc.year == 2026
    assert doc.document_name == "GF_2026_07_16_11_16_54"
    assert doc.published_at == datetime(2026, 7, 21, 22, 0, tzinfo=timezone.utc)
    assert doc.article_date == datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


@pytest.mark.unit
def test_documents_is_extra_string_normalized_to_bool(client):
    """The documents endpoint's string ``"False"`` becomes a real ``bool``."""
    doc = client.get_documents_by_bopa(2026, 82).documents[0]
    assert doc.is_extra is False


@pytest.mark.unit
def test_documents_sumari_percent_decoded(client):
    """``sumari`` is percent-decoded UTF-8 into the readable title."""
    doc = client.get_documents_by_bopa(2026, 82).documents[0]
    assert doc.title == (
        "Avís del 16-7-2026 pel qual es notifica al Sr. Haibin Pan, president "
        "de la societat OEC, SLU, que la Ministra de Presidència, Economia, "
        "Treball i Habitatge, va dictar un acte que afecta els seus interessos "
        "(Ref. SIT-C52/25)."
    )
    assert "%c3" not in doc.title


@pytest.mark.unit
def test_get_documents_returns_a_copy(client):
    """Mutating a returned page never corrupts the shared fixture state."""
    first = client.get_documents_by_bopa(2026, 82)
    first.documents.clear()
    assert len(client.get_documents_by_bopa(2026, 82).documents) == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    ("n", "expected"),
    [(7, "007"), (77, "077"), (777, "777"), (7777, "7777"), (0, "000")],
)
def test_pad3_only_pads_up_to_three_digits(n, expected):
    """``pad3`` pads 1-/2-digit numbers but leaves longer ones untouched."""
    assert pad3(n) == expected


@pytest.mark.unit
def test_build_pdf_url_matches_verified_examples(client):
    """Per-document PDF URLs match the two verified real folders."""
    assert client.build_pdf_url(2026, 77, "GLT_2026_07_06_11_34_08") == (
        "https://bopadocuments.blob.core.windows.net/bopa-documents/"
        "038077/pdf/GLT_2026_07_06_11_34_08.pdf"
    )
    assert client.build_pdf_url(2020, 60, "DOC_X") == (
        "https://bopadocuments.blob.core.windows.net/bopa-documents/"
        "032060/pdf/DOC_X.pdf"
    )


@pytest.mark.unit
def test_build_sumari_pdf_url_matches_verified_examples(client):
    """Sumari PDF URLs match the two verified real paths."""
    assert client.build_sumari_pdf_url(2026, 77) == (
        "https://bopadocuments.blob.core.windows.net/bopa-documents/"
        "sumaris/038/038077.pdf"
    )
    assert client.build_sumari_pdf_url(2020, 60) == (
        "https://bopadocuments.blob.core.windows.net/bopa-documents/"
        "sumaris/032/032060.pdf"
    )


@pytest.mark.unit
def test_fetch_content_falls_back_to_canned_html(client):
    """A document without a committed body gets the canned HTML stub."""
    content = client.fetch_content("https://example.invalid/whatever.html")
    assert isinstance(content, bytes)
    assert b"<html>" in content
    assert b"Mock BOPA document content." in content


@pytest.mark.unit
def test_fetch_content_serves_committed_real_body(client):
    """A document with a committed body under ``fixtures/bodies/`` is served it.

    The OEC, SLU edict body is what the analysis pipeline reads to match the
    ``OEC, SLU`` customer, so its real text must reach ``fetch_content``.
    """
    doc = client.get_documents_by_bopa(2026, 82).documents[0]
    content = client.fetch_content(doc.source_url)
    assert isinstance(content, bytes)
    assert b"OEC, SLU" in content
    assert content != client.fetch_content("https://example.invalid/x.html")


@pytest.mark.unit
def test_di_provider_returns_mock_in_mock_mode():
    """The DI provider returns the mock client when mode is 'mock'."""
    assert settings.BOPA_MODE == "mock"
    provided = get_bopa_client()
    assert isinstance(provided, MockBopaClient)
    assert isinstance(provided, BopaClient)


@pytest.mark.unit
def test_di_provider_rejects_unknown_mode(monkeypatch):
    """An unsupported mode fails loudly rather than silently misbehaving."""
    monkeypatch.setattr(settings, "BOPA_MODE", "bogus")
    with pytest.raises(RuntimeError):
        get_bopa_client()


@pytest.mark.unit
def test_di_provider_returns_live_in_live_mode(monkeypatch):
    """The DI provider returns the live client when mode is 'live'."""
    from app.core.dependencies import _live_bopa_client

    _live_bopa_client.cache_clear()
    monkeypatch.setattr(settings, "BOPA_MODE", "live")
    try:
        provided = get_bopa_client()
        assert isinstance(provided, LiveBopaClient)
        assert isinstance(provided, BopaClient)
        # Cached: the same instance is reused across requests.
        assert get_bopa_client() is provided
    finally:
        _live_bopa_client.cache_clear()
