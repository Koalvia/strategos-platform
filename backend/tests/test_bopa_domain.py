"""Tests for the BOPA domain: sync logic, persistence and the read API (issue #49).

These exercise ``BopaService.sync_latest`` against the fixture-backed
``MockBopaClient`` from #48 (no HTTP mocking needed at this layer) plus the read
endpoints through the real FastAPI app. Coverage per the issue's acceptance
criteria: a first sync populates bulletins + documents, a second sync is a no-op
(idempotency), one failing document download does not abort the rest of the
bulletin, and every read endpoint works against synced data.
"""

import pytest

from app.core.dependencies import get_bopa_client
from app.domains.bopa.models import BopaBulletin, BopaDocument
from app.domains.bopa.service import BopaService
from app.integrations.bopa.mock_client import MockBopaClient
from app.main import app

BOPA_URL = "/api/v1/bopa"


class _FailingFetchClient(MockBopaClient):
    """A mock client whose ``fetch_content`` raises for one specific document.

    Used to prove a single failing download is counted but does not abort the
    rest of the bulletin's sync.
    """

    def fetch_content(self, source_url: str) -> bytes:
        if "11_34_08" in source_url:
            raise RuntimeError("simulated download failure")
        return super().fetch_content(source_url)


@pytest.mark.integration
def test_sync_populates_bulletins_and_documents(db_session):
    """The first sync creates every fixture bulletin and its documents."""
    service = BopaService(db_session, MockBopaClient())
    result = service.sync_latest()

    # Two fixture bulletins (77 and 76 of 2026), each with the 2-document page.
    assert result.bulletins_synced == 2
    assert result.documents_synced == 4
    assert result.documents_failed == 0

    assert db_session.query(BopaBulletin).count() == 2
    assert db_session.query(BopaDocument).count() == 4

    bulletin = (
        db_session.query(BopaBulletin)
        .filter(BopaBulletin.year == 2026, BopaBulletin.num == 77)
        .one()
    )
    # totalCount from the fixture is higher than the documents actually returned.
    assert bulletin.total_document_count == 188
    assert bulletin.document_count == 2
    assert bulletin.sumari_pdf_url.endswith("sumaris/038/038077.pdf")

    # HTML documents have their body fetched and stored; the constructed pdf_url
    # points at the per-document blob.
    doc = bulletin.documents[0]
    assert doc.html_content is not None
    assert doc.pdf_url.endswith(f"/pdf/{doc.document_name}.pdf")


@pytest.mark.integration
def test_sync_is_idempotent(db_session):
    """A second back-to-back sync creates no new rows and re-fetches nothing."""
    service = BopaService(db_session, MockBopaClient())
    service.sync_latest()

    second = service.sync_latest()
    assert second.bulletins_synced == 0
    assert second.documents_synced == 0
    assert second.documents_failed == 0

    assert db_session.query(BopaBulletin).count() == 2
    assert db_session.query(BopaDocument).count() == 4


@pytest.mark.integration
def test_one_failing_document_does_not_abort_the_bulletin(db_session):
    """A single failing download is counted; the rest of the bulletin still syncs."""
    service = BopaService(db_session, _FailingFetchClient())
    result = service.sync_latest()

    # Both bulletins still created; one document per bulletin fails, one succeeds.
    assert result.bulletins_synced == 2
    assert result.documents_synced == 2
    assert result.documents_failed == 2

    assert db_session.query(BopaBulletin).count() == 2
    assert db_session.query(BopaDocument).count() == 2


@pytest.mark.integration
def test_read_endpoints_against_synced_data(client):
    """POST /sync then the three read endpoints all return the persisted data."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()

    sync = client.post(f"{BOPA_URL}/sync")
    assert sync.status_code == 200
    assert sync.json() == {
        "bulletins_synced": 2,
        "documents_synced": 4,
        "documents_failed": 0,
    }

    # List: most recently published first (num 77 published after num 76).
    listing = client.get(f"{BOPA_URL}/bulletins")
    assert listing.status_code == 200
    bulletins = listing.json()
    assert [b["num"] for b in bulletins] == [77, 76]
    assert bulletins[0]["document_count"] == 2
    assert "html_content" not in bulletins[0]

    # Detail: includes the documents, each without html_content.
    detail = client.get(f"{BOPA_URL}/bulletins/2026/77")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["documents"]) == 2
    assert "html_content" not in body["documents"][0]

    # Document detail: includes the stored html_content.
    document_id = body["documents"][0]["id"]
    doc = client.get(f"{BOPA_URL}/documents/{document_id}")
    assert doc.status_code == 200
    assert doc.json()["html_content"] is not None


@pytest.mark.integration
def test_list_filters_by_year_and_is_extra(client):
    """The year / is_extra query params narrow the listing."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # Only the extra bulletin (num 76) is is_extra=True in the fixtures.
    extra = client.get(f"{BOPA_URL}/bulletins", params={"is_extra": True})
    assert extra.status_code == 200
    assert [b["num"] for b in extra.json()] == [76]

    none = client.get(f"{BOPA_URL}/bulletins", params={"year": 1999})
    assert none.status_code == 200
    assert none.json() == []


@pytest.mark.integration
def test_unknown_bulletin_and_document_return_404(client):
    """Missing bulletin / document ids surface as 404s."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()

    assert client.get(f"{BOPA_URL}/bulletins/1999/1").status_code == 404
    assert client.get(f"{BOPA_URL}/documents/999999").status_code == 404
