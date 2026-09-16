"""Tests for the BOPA sync surviving a malformed upstream bulletin.

Bulletin 89/2026 shipped one document whose ``organisme`` / ``organismePare``
were ``null``. The transport DTO rejected the whole issue and, because
``sync_latest`` had no per-bulletin isolation, the exception aborted the daily
run before that issue or any later one was stored — six weeks of bulletins never
reached the platform. Two guarantees now hold:

* a ``null`` (or missing) classification label validates to ``""`` instead of
  failing the page;
* a bulletin that still fails for any reason is logged, counted in
  ``bulletins_failed`` and skipped, while the bulletins after it sync normally
  and the failed one is retried on the next run.
"""

import json
from pathlib import Path

import pytest

from app.domains.bopa.models import BopaBulletin, BopaDocument
from app.domains.bopa.service import BopaService
from app.integrations.bopa import mock_client
from app.integrations.bopa.mock_client import MockBopaClient
from app.integrations.bopa.models import BopaBulletinListItem, BopaDocumentsPage

_FIXTURE_PATH = (
    Path(mock_client.__file__).parent / "fixtures" / "documents_by_bopa_82_2026.json"
)

# A second issue, listed after the fixture's 82/2026, so the sync has a bulletin
# that comes *after* a failing one.
_SECOND_ISSUE = BopaBulletinListItem.model_validate(
    {
        "num": 83,
        "numBOPA": "Núm. 83 any 2026",
        "isExtra": False,
        "dataPublicacio": "2026-07-17T00:00:00",
    }
)


def _raw_page() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_null_classification_labels_validate_to_empty_strings():
    """A document with ``null`` labels no longer fails its whole page."""
    raw = _raw_page()
    first = raw["paginatedDocuments"][0]["document"]
    first["organisme"] = None
    first["organismePare"] = None

    page = BopaDocumentsPage.model_validate(raw)

    assert page.documents[0].organisme == ""
    assert page.documents[0].organisme_pare == ""
    # The other documents keep their real labels.
    assert page.documents[1].organisme
    assert page.documents[1].organisme_pare


@pytest.mark.unit
def test_missing_classification_labels_default_to_empty_strings():
    """A label key absent from the payload is treated like ``null``."""
    raw = _raw_page()
    document = raw["paginatedDocuments"][0]["document"]
    del document["tema"]
    del document["temaPare"]

    page = BopaDocumentsPage.model_validate(raw)

    assert page.documents[0].tema == ""
    assert page.documents[0].tema_pare == ""


class _TwoIssueClient(MockBopaClient):
    """Lists the fixture issue (82) plus a second one (83)."""

    def get_month_bulletins(self, reference_date):
        return super().get_month_bulletins(reference_date) + [_SECOND_ISSUE]


class _FirstIssueBrokenClient(_TwoIssueClient):
    """The documents call for issue 82 raises, as a malformed payload would."""

    def get_documents_by_bopa(self, year, num):
        if num == 82:
            raise ValueError("simulated malformed upstream payload")
        return super().get_documents_by_bopa(year, num)


@pytest.mark.integration
def test_failing_bulletin_is_skipped_and_later_ones_still_sync(db_session):
    """One broken issue is counted and skipped; the next issue syncs in full."""
    result = BopaService(db_session, _FirstIssueBrokenClient()).sync_latest()

    assert result.bulletins_failed == 1
    assert result.bulletins_synced == 1
    assert result.documents_synced == 3
    assert result.documents_failed == 0

    # Only the healthy issue was stored; nothing of the broken one was left.
    assert {b.num for b in db_session.query(BopaBulletin)} == {83}
    assert db_session.query(BopaDocument).count() == 3


@pytest.mark.integration
def test_skipped_bulletin_is_synced_once_upstream_recovers(db_session):
    """The issue skipped on one run is picked up by the next healthy run."""
    BopaService(db_session, _FirstIssueBrokenClient()).sync_latest()

    result = BopaService(db_session, _TwoIssueClient()).sync_latest()

    assert result.bulletins_failed == 0
    assert result.bulletins_synced == 1
    assert result.documents_synced == 3
    assert {b.num for b in db_session.query(BopaBulletin)} == {82, 83}
    assert db_session.query(BopaDocument).count() == 6
