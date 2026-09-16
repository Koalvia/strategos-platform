"""Tests for excluding BOPA signature blocks from customer matching.

BOPA's HTML export closes almost every document with a ``<p class="Data">``
place/date line followed by one or more ``<p class="signatura">`` blocks holding
the signer's name and role. A customer whose name appears **only** there is
signing the edict as an official (a minister, a comú cònsol, a court president),
not being mentioned as a party — in production one such customer alone produced
nine alerts across two bulletins. Signature blocks are therefore stripped before
the whole-word rule runs (see ``app.domains.bopa.matching``); a mention anywhere
else — title, body, tables, annexes after the signature — still matches.

The unit tests exercise ``_match_document`` with lightweight stand-ins (like
``test_bopa_match_precision.py``); the integration test covers the per-customer
search, whose DB-side ILIKE prefilter still sees the signature text.
"""

from datetime import datetime

import pytest

from app.domains.bopa.matching import searchable_text, strip_signature_blocks
from app.domains.bopa.models import BopaDocument
from app.domains.bopa.service import BopaService
from app.domains.bopa.tasks import _match_document
from app.integrations.bopa.mock_client import MockBopaClient

# A fictional official whose name is also a customer of the firm.
SIGNER = "Marta Vidal Roca"

# The closing sequence of a real BOPA edict: formula, place/date line, signature.
_CLOSING = (
    '<p class="Body-text">Cosa que es fa pública per a coneixement general.</p>'
    '<p class="Data">Andorra la Vella, 22 de juliol del 2026</p>'
    f'<p class="signatura">{SIGNER}<br />'
    "Presidenta del Consell Superior de la Justícia</p>"
)


def _html(*paragraphs: str, closing: str = _CLOSING) -> str:
    body = "".join(f'<p class="Body-text">{p}</p>' for p in paragraphs)
    return f'<html><body><div id="_idContainer000">{body}{closing}</div></body></html>'


class _Doc:
    """A minimal stand-in for BopaDocument (only the fields matching reads)."""

    def __init__(self, doc_id: int, title: str, body: str):
        self.id = doc_id
        self.title = title
        self.html_content = body


def _customer(customer_id: str, name: str, nif: str | None = None):
    return type("C", (), {"id": customer_id, "name": name, "nif": nif})()


def _project(project_id: str, customer_id: str, name: str):
    return type(
        "P", (), {"id": project_id, "customer_id": customer_id, "name": name}
    )()


@pytest.mark.unit
def test_signature_block_is_removed_from_searchable_text():
    """The signer's name/role paragraph is gone; the rest of the body survives."""
    html = _html("Es convoca un concurs per al subministrament de mobiliari.")
    text = searchable_text("Edicte del 22-7-2026", html)

    assert SIGNER not in text
    assert "Presidenta del Consell" not in text
    assert "subministrament de mobiliari" in text
    # The place/date line is not a signature block and is left alone.
    assert "Andorra la Vella, 22 de juliol del 2026" in text


@pytest.mark.unit
def test_strip_handles_missing_body():
    assert strip_signature_blocks(None) == ""
    assert strip_signature_blocks("") == ""


@pytest.mark.unit
def test_customer_named_only_in_the_signature_does_not_match():
    """An official who merely signs the edict is not a match, so no alert."""
    doc = _Doc(1, "Edicte de convocatòria", _html("Concurs nacional públic."))
    assert _match_document(doc, [_customer("c1", SIGNER)], []) == []


@pytest.mark.unit
def test_customer_named_in_the_body_and_the_signature_still_matches():
    """A genuine mention elsewhere is kept even though the signature is stripped."""
    doc = _Doc(
        1, "Acord", _html(f"S'accepta la renúncia presentada per {SIGNER}.")
    )
    matches = _match_document(doc, [_customer("c1", SIGNER)], [])
    assert len(matches) == 1
    assert matches[0].matched_term == SIGNER


@pytest.mark.unit
def test_customer_named_in_the_title_matches_even_if_the_body_only_signs():
    """The title is never stripped, so a titled mention still matches."""
    doc = _Doc(1, f"Acord de nomenament de la Sra. {SIGNER}", _html("Text."))
    assert len(_match_document(doc, [_customer("c1", SIGNER)], [])) == 1


@pytest.mark.unit
def test_every_signature_block_is_stripped():
    """A comú-style double signature (two blocks, several lines each) is removed."""
    closing = (
        '<p class="Data">Escaldes-Engordany, Casa Comuna, 31 d’agost de 2026</p>'
        '<p class="signatura">Vist i plau<br />La cònsol major<br />Anna Pons Grau</p>'
        '<p class="signatura">P. o. de la Junta de Govern<br />'
        "La secretària general<br />Laia Torres Molné</p>"
    )
    doc = _Doc(1, "Edicte", _html("Licitació d’obres.", closing=closing))
    customers = [_customer("c1", "Anna Pons Grau"), _customer("c2", "Laia Torres Molné")]
    assert _match_document(doc, customers, []) == []


@pytest.mark.unit
def test_content_after_the_signature_still_matches():
    """Annexes that follow the signature (tables, lists) are not stripped."""
    html = _html("Adjudicació de subvencions.") + (
        '<p class="Body-text">Annex 1. Beneficiaris</p>'
        "<table><tr><td>Treball Temporal, SL</td><td>3.000,00 €</td></tr></table>"
    )
    doc = _Doc(1, "Edicte", html)
    matches = _match_document(doc, [_customer("c1", "Treball Temporal, SL")], [])
    assert len(matches) == 1


@pytest.mark.unit
def test_project_named_only_in_the_signature_does_not_match():
    """Projects (often named after the customer) follow the same rule."""
    doc = _Doc(1, "Avís de convocatòria", _html("Prova oficial del diploma."))
    customers = [_customer("c1", "Some Other Name")]
    projects = [_project("p1", "c1", SIGNER)]
    assert _match_document(doc, customers, projects) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "block",
    [
        f"<P CLASS='signatura'>{SIGNER}<br />Ministra</P>",
        f'<p class="Body-text signatura">{SIGNER}</p>',
        f"<p id='s1' class=signatura>{SIGNER}</p>",
        f'<p class="signatura">\n  {SIGNER}\n  <br />\n  Cònsol major\n</p >',
    ],
)
def test_signature_markup_variants_are_recognised(block: str):
    """Case, quoting, extra classes, attribute order and line breaks all count."""
    assert SIGNER not in strip_signature_blocks(f"<div><p>Intro.</p>{block}</div>")


@pytest.mark.unit
def test_paragraph_without_the_signature_class_is_kept():
    """Only the ``signatura`` class is stripped — not every trailing paragraph."""
    html = f'<p class="Body-text">{SIGNER} sol·licita la llicència.</p>'
    assert SIGNER in strip_signature_blocks(html)


def _stored_doc(bulletin_id: int, title: str, body: str, name: str) -> BopaDocument:
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
        article_date=datetime(2026, 7, 22),
        source_url=f"https://example.com/{name}",
        pdf_url=f"https://example.com/{name}.pdf",
    )


@pytest.mark.integration
def test_client_search_excludes_signature_only_documents(
    db_session, bopa_bulletin_factory
):
    """The per-customer search drops documents the client merely signed.

    The ILIKE prefilter runs on the raw ``html_content`` (signature included), so
    this proves the authoritative whole-word pass applies the stripped text.
    """
    bulletin_id = bopa_bulletin_factory().id
    signed = _stored_doc(bulletin_id, "Edicte", _html("Concurs."), "signed.html")
    mentioned = _stored_doc(
        bulletin_id, "Acord", _html(f"Es nomena {SIGNER} vocal."), "mentioned.html"
    )
    db_session.add_all([signed, mentioned])
    db_session.commit()

    page = BopaService(db_session, MockBopaClient()).search_documents_by_client(
        nombre=SIGNER
    )

    assert {item.document_name for item in page.items} == {"mentioned.html"}
    assert page.total == 1
