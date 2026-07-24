"""Tests for pruning false-positive BOPA matches and the whole-word client search.

Two guarantees that BOPA results only ever concern our own customers:

* :func:`app.domains.bopa.tasks.prune_false_positive_matches` removes stored
  matches (and their alerts) whose ``matched_term`` no longer appears as whole
  word(s) in the document — the cleanup for rows created under the old
  substring rule.
* :meth:`BopaService.search_documents_by_client` applies the same whole-word
  rule, so the per-customer document search never surfaces a substring-only
  false positive either.
"""

from datetime import datetime

import pytest

from app.domains.alerts.models import Alert, AlertStatus, AlertType
from app.domains.bopa import tasks
from app.domains.bopa.models import BopaDocument, BopaMatch
from app.domains.bopa.service import BopaService
from app.integrations.bopa.mock_client import MockBopaClient


def _doc(bulletin_id, title, body, name):
    return BopaDocument(
        bulletin_id=bulletin_id,
        title=title,
        html_content=body,
        document_name=name,
        file_type="html",
        organisme="Org",
        organisme_pare="Gov",
        tema="Tema",
        tema_pare="TemaPare",
        article_date=datetime(2026, 1, 1),
        source_url=f"https://example.com/{name}",
        pdf_url=f"https://example.com/{name}.pdf",
    )


@pytest.mark.integration
def test_prune_removes_substring_false_positive_and_its_alert(
    db_session, monkeypatch, bopa_bulletin_factory
):
    """A match whose term is only a substring is deleted with its alert; a
    genuine whole-word match (and its alert) is kept. Second run is a no-op."""
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)

    bulletin_id = bopa_bulletin_factory().id
    # "Ferrer" is only a substring of "Ferreria" -> false positive.
    bad_doc = _doc(bulletin_id, "Obertura", "Nova Ferreria del Pont", "bad.html")
    # "Fontaneria Puigcerdà SL" appears as whole words -> genuine.
    good_doc = _doc(
        bulletin_id, "Edicte", "Fontaneria Puigcerdà SL inscrita", "good.html"
    )
    db_session.add_all([bad_doc, good_doc])
    db_session.flush()

    bad = BopaMatch(
        customer_id="cust-x", document_id=bad_doc.id, matched_term="Ferrer"
    )
    good = BopaMatch(
        customer_id="cust-y",
        document_id=good_doc.id,
        matched_term="Fontaneria Puigcerdà SL",
    )
    db_session.add_all([bad, good])
    db_session.flush()
    db_session.add_all(
        [
            Alert(
                customer_id="cust-x",
                alert_type=AlertType.BOPA,
                bopa_match_id=bad.id,
                status=AlertStatus.NEW,
            ),
            Alert(
                customer_id="cust-y",
                alert_type=AlertType.BOPA,
                bopa_match_id=good.id,
                status=AlertStatus.NEW,
            ),
        ]
    )
    db_session.commit()
    good_id = good.id

    removed = tasks.prune_false_positive_matches()
    assert removed == 1

    remaining = db_session.query(BopaMatch).all()
    assert [m.matched_term for m in remaining] == ["Fontaneria Puigcerdà SL"]
    # The false positive's alert is gone; the genuine one's alert stays.
    alerts = db_session.query(Alert).all()
    assert len(alerts) == 1
    assert alerts[0].bopa_match_id == good_id

    # Idempotent: nothing left to prune.
    assert tasks.prune_false_positive_matches() == 0


@pytest.mark.integration
def test_client_search_excludes_substring_only_documents(
    db_session, bopa_bulletin_factory
):
    """The per-customer search returns whole-word hits only, not substrings."""
    bulletin_id = bopa_bulletin_factory().id
    whole = _doc(bulletin_id, "Edicte", "El Sr. Ferrer, SL consta", "whole.html")
    substring = _doc(bulletin_id, "Anunci", "Nova Ferreria del Pont", "sub.html")
    db_session.add_all([whole, substring])
    db_session.commit()

    service = BopaService(db_session, MockBopaClient())
    page = service.search_documents_by_client(nombre="Ferrer")

    names = {item.document_name for item in page.items}
    assert names == {"whole.html"}
    assert page.total == 1


@pytest.mark.unit
def test_prune_script_delegates_to_task(monkeypatch):
    """The one-off script runs the prune task and reports its count."""
    from scripts import prune_bopa_false_positives

    monkeypatch.setattr(
        prune_bopa_false_positives, "prune_false_positive_matches", lambda: 3
    )
    assert prune_bopa_false_positives.main() == 3
