"""Tests for the BOPA domain: sync logic, persistence and the read API (issue #49).

These exercise ``BopaService.sync_latest`` against the fixture-backed
``MockBopaClient`` from #48 (no HTTP mocking needed at this layer) plus the read
endpoints through the real FastAPI app. Coverage per the issue's acceptance
criteria: a first sync populates bulletins + documents, a second sync is a no-op
(idempotency), one failing document download does not abort the rest of the
bulletin, and every read endpoint works against synced data.

The fixture is the latest published bulletin (num 82 of 2026) with three real
documents drawn from it: the OEC, SLU notification edict (``GF_...``, which ships
a committed HTML body), a Consell General tender edict (``CGC_...``) and a Govern
regulation decree (``GR_...``); the latter two have no committed body, so they
receive the mock's canned stub. ``totalCount`` (209) deliberately exceeds the
three documents returned, mirroring the real API quirk.
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
        if "CGC_2026_07_16_11_25_58" in source_url:
            raise RuntimeError("simulated download failure")
        return super().fetch_content(source_url)


# A body with characters that only survive a correct UTF-16 round-trip.
_UTF16_BODY_TEXT = (
    "<html><head><title>BOPA (UTF-16)</title></head>"
    "<body><p>Retirada de la reserva — Andorra: â‚¬ Ã± Ã§</p></body></html>"
)


class _Utf16FetchClient(MockBopaClient):
    """A mock client whose ``fetch_content`` returns UTF-16-with-BOM bodies.

    Mirrors the production surprise from #69, where a subset of BOPA's own HTML
    exports are served as UTF-16 rather than UTF-8.
    """

    def fetch_content(self, source_url: str) -> bytes:
        return _UTF16_BODY_TEXT.encode("utf-16")


@pytest.mark.integration
def test_sync_populates_bulletins_and_documents(db_session):
    """The first sync creates the fixture bulletin and its documents."""
    service = BopaService(db_session, MockBopaClient())
    result = service.sync_latest()

    # One fixture bulletin (num 82 of 2026) carrying its 3-document page.
    assert result.bulletins_synced == 1
    assert result.documents_synced == 3
    assert result.documents_failed == 0

    assert db_session.query(BopaBulletin).count() == 1
    assert db_session.query(BopaDocument).count() == 3

    bulletin = (
        db_session.query(BopaBulletin)
        .filter(BopaBulletin.year == 2026, BopaBulletin.num == 82)
        .one()
    )
    # totalCount from the fixture is higher than the documents actually returned.
    assert bulletin.total_document_count == 209
    assert bulletin.document_count == 3
    assert bulletin.sumari_pdf_url.endswith("sumaris/038/038082.pdf")

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

    assert db_session.query(BopaBulletin).count() == 1
    assert db_session.query(BopaDocument).count() == 3


@pytest.mark.integration
def test_one_failing_document_does_not_abort_the_bulletin(db_session):
    """A single failing download is counted; the rest of the bulletin still syncs."""
    service = BopaService(db_session, _FailingFetchClient())
    result = service.sync_latest()

    # The bulletin is created; one of its three documents fails, two succeed.
    assert result.bulletins_synced == 1
    assert result.documents_synced == 2
    assert result.documents_failed == 1

    assert db_session.query(BopaBulletin).count() == 1
    assert db_session.query(BopaDocument).count() == 2


@pytest.mark.integration
def test_sync_decodes_utf16_documents_instead_of_failing(db_session):
    """A UTF-16-with-BOM body is decoded correctly, not counted as failed (#69)."""
    service = BopaService(db_session, _Utf16FetchClient())
    result = service.sync_latest()

    # All three HTML documents decode; none is lost to the encoding mismatch.
    assert result.documents_synced == 3
    assert result.documents_failed == 0
    assert db_session.query(BopaDocument).count() == 3

    # The stored body matches the original text, BOM stripped by the utf-16 codec.
    doc = db_session.query(BopaDocument).first()
    assert doc.html_content == _UTF16_BODY_TEXT
    assert "﻿" not in doc.html_content


@pytest.mark.integration
def test_sync_backfills_previously_incomplete_bulletins(db_session):
    """A bulletin left short by a failed download is backfilled on a later run (#69)."""
    # First run: one document fails to download and is dropped.
    failing = BopaService(db_session, _FailingFetchClient())
    first = failing.sync_latest()
    assert first.bulletins_synced == 1
    assert first.documents_synced == 2
    assert first.documents_failed == 1
    assert db_session.query(BopaDocument).count() == 2

    # Second run with a healthy client backfills only the one missing document
    # into the already-stored bulletin — the bulletin row is not recreated.
    healthy = BopaService(db_session, MockBopaClient())
    second = healthy.sync_latest()
    assert second.bulletins_synced == 0
    assert second.documents_synced == 1
    assert second.documents_failed == 0
    assert db_session.query(BopaBulletin).count() == 1
    assert db_session.query(BopaDocument).count() == 3

    # Third run is a no-op backfill: nothing missing, no duplicate rows.
    third = healthy.sync_latest()
    assert third.bulletins_synced == 0
    assert third.documents_synced == 0
    assert third.documents_failed == 0
    assert db_session.query(BopaDocument).count() == 3


@pytest.mark.integration
def test_read_endpoints_against_synced_data(client):
    """POST /sync then the three read endpoints all return the persisted data."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()

    sync = client.post(f"{BOPA_URL}/sync")
    assert sync.status_code == 200
    assert sync.json() == {
        "bulletins_synced": 1,
        "documents_synced": 3,
        "documents_failed": 0,
    }

    # List: the single stored bulletin.
    listing = client.get(f"{BOPA_URL}/bulletins")
    assert listing.status_code == 200
    bulletins = listing.json()
    assert [b["num"] for b in bulletins] == [82]
    assert bulletins[0]["document_count"] == 3
    assert "html_content" not in bulletins[0]

    # Detail: includes the documents, each without html_content.
    detail = client.get(f"{BOPA_URL}/bulletins/2026/82")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["documents"]) == 3
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

    # The fixture bulletin (num 82) is not an extra edition.
    regular = client.get(f"{BOPA_URL}/bulletins", params={"is_extra": False})
    assert regular.status_code == 200
    assert [b["num"] for b in regular.json()] == [82]

    extra = client.get(f"{BOPA_URL}/bulletins", params={"is_extra": True})
    assert extra.status_code == 200
    assert extra.json() == []

    none = client.get(f"{BOPA_URL}/bulletins", params={"year": 1999})
    assert none.status_code == 200
    assert none.json() == []


@pytest.mark.integration
def test_unknown_bulletin_and_document_return_404(client):
    """Missing bulletin / document ids surface as 404s."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()

    assert client.get(f"{BOPA_URL}/bulletins/1999/1").status_code == 404
    assert client.get(f"{BOPA_URL}/documents/999999").status_code == 404


# The fixture bulletin (num 82 of 2026) carries three documents spanning three
# distinct organismes / temes:
# * OEC, SLU notification:  organisme "Notificacions", tema "Govern",
#   tema_pare "15. Notificacions", organisme_pare "03. Govern". Its committed
#   body names the society "OEC, SLU".
# * Consell General tender: organisme "Concursos i subhastes", tema "Serveis",
#   tema_pare "08. Concursos", organisme_pare "02. Consell General".
# * Govern regulation:      organisme "Reglaments", tema "Reglaments",
#   tema_pare "20. Reglaments", organisme_pare "03. Govern".
# The last two have no committed body, so they receive the mock's canned stub
# (which contains the word "content").


@pytest.mark.integration
def test_search_returns_all_documents_with_bulletin_metadata(client):
    """With no filters, every synced document is returned with its bulletin's year/num."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(f"{BOPA_URL}/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Every row threads its owning bulletin's year/num and omits html_content.
    for item in body["items"]:
        assert item["bulletin_year"] == 2026
        assert item["bulletin_num"] == 82
        assert "html_content" not in item


@pytest.mark.integration
def test_search_filters_by_query_organisme_and_tema(client):
    """q substring (case-insensitive), organisme and tema each narrow results."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # q: case-insensitive substring match on title (only the tender is a "concurs").
    by_q = client.get(f"{BOPA_URL}/documents", params={"q": "concurs"})
    assert by_q.status_code == 200
    assert by_q.json()["total"] == 1
    assert all("concurs" in i["title"].lower() for i in by_q.json()["items"])

    # q also matches the stored HTML body: "content" appears only in the mock's
    # canned body ("...Mock BOPA document content..."), which backs the two
    # documents without a committed body, never in any fixture title — so a
    # non-zero result proves body search works, not just title search.
    by_body = client.get(f"{BOPA_URL}/documents", params={"q": "content"})
    assert by_body.status_code == 200
    assert by_body.json()["total"] == 2
    assert all(
        "content" not in i["title"].lower() for i in by_body.json()["items"]
    )

    # organisme: exact-match facet (one document per organisme).
    by_org = client.get(
        f"{BOPA_URL}/documents", params={"organisme": "Concursos i subhastes"}
    )
    assert by_org.status_code == 200
    assert by_org.json()["total"] == 1
    assert all(
        i["organisme"] == "Concursos i subhastes" for i in by_org.json()["items"]
    )

    # tema: exact-match facet.
    by_tema = client.get(f"{BOPA_URL}/documents", params={"tema": "Reglaments"})
    assert by_tema.status_code == 200
    assert by_tema.json()["total"] == 1
    assert all(i["tema"] == "Reglaments" for i in by_tema.json()["items"])

    # No match => empty page with total 0.
    none = client.get(f"{BOPA_URL}/documents", params={"organisme": "Nope"})
    assert none.status_code == 200
    assert none.json() == {"items": [], "total": 0}


@pytest.mark.integration
def test_search_filters_by_parent_facets_year_and_dates(client):
    """organisme_pare / tema_pare, year, and the date bounds each filter correctly."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # organisme_pare shared by the two Govern documents (OEC + regulation).
    by_org_pare = client.get(
        f"{BOPA_URL}/documents", params={"organisme_pare": "03. Govern"}
    )
    assert by_org_pare.json()["total"] == 2

    # tema_pare uniquely identifies the notification document.
    by_tema_pare = client.get(
        f"{BOPA_URL}/documents", params={"tema_pare": "15. Notificacions"}
    )
    assert by_tema_pare.json()["total"] == 1

    # year: matches the bulletin's year via the join.
    assert client.get(f"{BOPA_URL}/documents", params={"year": 2026}).json()[
        "total"
    ] == 3
    assert client.get(f"{BOPA_URL}/documents", params={"year": 1999}).json()[
        "total"
    ] == 0

    # date_from / date_to inclusively bound article_date. The tender and the
    # regulation are dated 2026-07-14; the OEC notification is dated 2026-07-15.
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_from": "2026-07-14"}
    ).json()["total"] == 3
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_to": "2026-07-15"}
    ).json()["total"] == 3
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_from": "2026-07-15"}
    ).json()["total"] == 1
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_to": "2026-07-14"}
    ).json()["total"] == 2
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_from": "2026-07-16"}
    ).json()["total"] == 0
    assert client.get(
        f"{BOPA_URL}/documents", params={"date_to": "2026-07-13"}
    ).json()["total"] == 0


@pytest.mark.integration
def test_search_combined_filters(client):
    """Combined filters intersect (AND semantics)."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(
        f"{BOPA_URL}/documents",
        params={"organisme": "Reglaments", "tema": "Reglaments", "year": 2026},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # A contradictory combination yields nothing.
    empty = client.get(
        f"{BOPA_URL}/documents",
        params={"organisme": "Reglaments", "tema": "Serveis"},
    )
    assert empty.json()["total"] == 0


@pytest.mark.integration
def test_search_query_combines_with_facet(client):
    """The free-text q intersects (AND) with a metadata facet, and misses are empty."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    # "content" matches the two canned-body documents; the organisme facet
    # narrows it to the single regulation document.
    combined = client.get(
        f"{BOPA_URL}/documents",
        params={"q": "content", "organisme": "Reglaments"},
    )
    assert combined.status_code == 200
    body = combined.json()
    assert body["total"] == 1
    assert all(i["organisme"] == "Reglaments" for i in body["items"])

    # A term in neither the title nor the HTML body yields nothing.
    none = client.get(
        f"{BOPA_URL}/documents", params={"q": "zzz-nonexistent-term"}
    )
    assert none.json() == {"items": [], "total": 0}


@pytest.mark.integration
def test_search_pagination_total_is_full_count(client):
    """limit/offset page the items while total reflects the full match count."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    page1 = client.get(f"{BOPA_URL}/documents", params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    assert page1.json()["total"] == 3
    assert len(page1.json()["items"]) == 2

    page2 = client.get(f"{BOPA_URL}/documents", params={"limit": 2, "offset": 2})
    assert page2.json()["total"] == 3
    assert len(page2.json()["items"]) == 1

    # The two pages are disjoint and together cover all three documents.
    ids = {i["id"] for i in page1.json()["items"]} | {
        i["id"] for i in page2.json()["items"]
    }
    assert len(ids) == 3


@pytest.mark.integration
def test_document_filters_endpoint(client):
    """The filters endpoint returns sorted, deduplicated facet values and is resolvable."""
    app.dependency_overrides[get_bopa_client] = lambda: MockBopaClient()
    client.post(f"{BOPA_URL}/sync")

    resp = client.get(f"{BOPA_URL}/documents/filters")
    # Not shadowed by /documents/{document_id} (which would 422 on "filters").
    assert resp.status_code == 200
    body = resp.json()
    assert body["organisme"] == [
        "Concursos i subhastes",
        "Notificacions",
        "Reglaments",
    ]
    assert body["tema"] == ["Govern", "Reglaments", "Serveis"]
    assert body["organisme_pare"] == ["02. Consell General", "03. Govern"]
    assert body["tema_pare"] == [
        "08. Concursos",
        "15. Notificacions",
        "20. Reglaments",
    ]


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
    assert body["bulletin_num"] == 82
    assert body["html_content"] is not None
