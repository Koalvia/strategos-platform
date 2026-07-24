"""Tests for the whole-word rule in the per-customer BOPA document search.

``BopaService.search_documents_by_client`` must return a document only when one
of the client's terms appears as complete word(s) — the same rule the analyzer
uses (see ``app.domains.bopa.matching``) — so the customer detail page never
surfaces a loose-substring false positive for an entity that is not the client.
"""

from datetime import datetime

import pytest

from app.domains.bopa.models import BopaDocument
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
