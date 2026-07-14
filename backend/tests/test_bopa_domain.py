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


# The two fixture bulletins (77 and 76 of 2026) share the same 2-document page,
# so a full sync yields 4 documents drawn from 2 distinct organismes / temes.
# Convenis internacionals: organisme "Convenis internacionals", tema
# "Convenis internacionals", tema_pare "11. Convenis internacionals".
# Finances:               organisme "Ministeri de Finances", tema "Edictes",
#                         tema_pare "05. Edictes". Both share organisme_pare
# "03. Govern".


@pytest.mark.integration
def test_search_returns_all_documents_with_bulletin_metadata(client):
    """With no filters, every synced document is returned with its bulletin's year/num."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(f"{BOPA_URL}/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert len(body["items"]) == 4
    # Every row threads its owning bulletin's year/num and omits html_content.
    for item in body["items"]:
        assert item["bulletin_year"] == 2026
        assert item["bulletin_num"] in (76, 77)
        assert "html_content" not in item


@pytest.mark.integration
def test_search_filters_by_query_organisme_and_tema(client):
    """q substring (case-insensitive), organisme and tema each narrow results."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # q: case-insensitive substring match on title.
    by_q = client.get(f"{BOPA_URL}/documents", params={"q": "conveni"})
    assert by_q.status_code == 200
    assert by_q.json()["total"] == 2
    assert all("conveni" in i["title"].lower() for i in by_q.json()["items"])

    # organisme: exact-match facet (one distinct organisme per bulletin => 2 rows).
    by_org = client.get(
        f"{BOPA_URL}/documents", params={"organisme": "Ministeri de Finances"}
    )
    assert by_org.status_code == 200
    assert by_org.json()["total"] == 2
    assert all(
        i["organisme"] == "Ministeri de Finances" for i in by_org.json()["items"]
    )

    # tema: exact-match facet.
    by_tema = client.get(f"{BOPA_URL}/documents", params={"tema": "Edictes"})
    assert by_tema.status_code == 200
    assert by_tema.json()["total"] == 2
    assert all(i["tema"] == "Edictes" for i in by_tema.json()["items"])

    # No match => empty page with total 0.
    none = client.get(f"{BOPA_URL}/documents", params={"organisme": "Nope"})
    assert none.status_code == 200
    assert none.json() == {"items": [], "total": 0}


@pytest.mark.integration
def test_search_filters_by_parent_facets_year_and_dates(client):
    """organisme_pare / tema_pare, year, and the date bounds each filter correctly."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # organisme_pare shared by all 4 documents.
    by_org_pare = client.get(
        f"{BOPA_URL}/documents", params={"organisme_pare": "03. Govern"}
    )
    assert by_org_pare.json()["total"] == 4

    # tema_pare distinguishes the two document kinds.
    by_tema_pare = client.get(
        f"{BOPA_URL}/documents", params={"tema_pare": "05. Edictes"}
    )
    assert by_tema_pare.json()["total"] == 2

    # year: matches the bulletins' year via the join.
    assert client.get(f"{BOPA_URL}/documents", params={"year": 2026}).json()[
        "total"
    ] == 4
    assert client.get(f"{BOPA_URL}/documents", params={"year": 1999}).json()[
        "total"
    ] == 0

    # date_from / date_to inclusively bound article_date (fixtures use 2026-07-05).
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_from": "2026-07-05"}
    ).json()["total"] == 4
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_to": "2026-07-05"}
    ).json()["total"] == 4
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_from": "2026-07-06"}
    ).json()["total"] == 0
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_to": "2026-07-04"}
    ).json()["total"] == 0


@pytest.mark.integration
def test_search_combined_filters(client):
    """Combined filters intersect (AND semantics)."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(
        f"{BOPA_URL}/documents",
        params={"organisme": "Ministeri de Finances", "tema": "Edictes", "year": 2026},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    # A contradictory combination yields nothing.
    empty = client.get(
        f"{BOPA_URL}/documents",
        params={"organisme": "Ministeri de Finances", "tema": "Convenis internacionals"},
    )
    assert empty.json()["total"] == 0


@pytest.mark.integration
def test_search_pagination_total_is_full_count(client):
    """limit/offset page the items while total reflects the full match count."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    page1 = client.get(f"{BOPA_URL}/documents", params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    assert page1.json()["total"] == 4
    assert len(page1.json()["items"]) == 2

    page2 = client.get(f"{BOPA_URL}/documents", params={"limit": 2, "offset": 2})
    assert page2.json()["total"] == 4
    assert len(page2.json()["items"]) == 2

    # The two pages are disjoint and together cover all four documents.
    ids = {i["id"] for i in page1.json()["items"]} | {
        i["id"] for i in page2.json()["items"]
    }
    assert len(ids) == 4


@pytest.mark.integration
def test_document_filters_endpoint(client):
    """The filters endpoint returns sorted, deduplicated facet values and is resolvable."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(f"{BOPA_URL}/documents/filters")
    # Not shadowed by /documents/{document_id} (which would 422 on "filters").
    assert resp.status_code == 200
    body = resp.json()
    assert body["organisme"] == ["Convenis internacionals", "Ministeri de Finances"]
    assert body["tema"] == ["Convenis internacionals", "Edictes"]
    assert body["organisme_pare"] == ["03. Govern"]
    assert body["tema_pare"] == ["05. Edictes", "11. Convenis internacionals"]


@pytest.mark.integration
def test_document_detail_carries_bulletin_year_and_num(client):
    """GET /documents/{id} inherits bulletin_year/bulletin_num from DocumentSummary."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    document_id = client.get(f"{BOPA_URL}/documents").json()["items"][0]["id"]
    doc = client.get(f"{BOPA_URL}/documents/{document_id}")
    assert doc.status_code == 200
    body = doc.json()
    assert body["bulletin_year"] == 2026
    assert body["bulletin_num"] in (76, 77)
    assert body["html_content"] is not None
