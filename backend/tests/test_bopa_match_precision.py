"""Tests for the BOPA match precision rule (whole-word name/NIF matching).

The analyzer must turn a document into a customer match — and therefore into an
alert with a link — only when the customer's **name** or **NIF** appears as
complete word(s), never as a loose substring. This is the guarantee that alerts
only ever concern our own customers: a substring false positive (a homonym, or a
name fragment inside a larger word) never becomes a match, so it is never
published and never gets a link.

These exercise ``_match_document`` directly with lightweight stand-ins (the same
duck-typed objects the analyzers pass in), so no DB or fixtures are needed.
"""

import pytest

from app.domains.bopa.tasks import _match_document


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
def test_name_substring_inside_a_word_is_not_matched():
    """A name that only appears inside a larger word does not match.

    "Ferrer" inside "Ferreria" used to match under the old naked-substring rule;
    the whole-word rule rejects it, so no false-positive alert is created.
    """
    doc = _Doc(1, "Obertura", "Nova Ferreria del Pont, SL")
    assert _match_document(doc, [_customer("c1", "Ferrer")], []) == []


@pytest.mark.unit
def test_full_name_as_whole_words_is_matched():
    """The full registered name appearing as whole words matches."""
    doc = _Doc(1, "Edicte", "La societat Fontaneria Puigcerdà SL queda inscrita")
    matches = _match_document(doc, [_customer("c1", "Fontaneria Puigcerdà SL")], [])
    assert len(matches) == 1
    assert matches[0].customer_id == "c1"
    assert matches[0].matched_term == "Fontaneria Puigcerdà SL"


@pytest.mark.unit
def test_name_matches_across_flexible_whitespace():
    """Tokens separated by newlines/extra spaces still match as whole words."""
    doc = _Doc(1, "Anunci", "... la mercantil OEC,\n  SLU hi consta ...")
    matches = _match_document(doc, [_customer("c1", "OEC, SLU")], [])
    assert len(matches) == 1


@pytest.mark.unit
def test_nif_matches_only_as_a_whole_token():
    """The NIF matches as a whole token, and labels the match when the name is
    absent — but never as a substring of a longer code."""
    customer = _customer("c1", "Zzz Improbable Name", nif="A123456")

    hit = _Doc(1, "Notificació", "Ref. NRT A123456 pendent de pagament")
    matches = _match_document(hit, [customer], [])
    assert len(matches) == 1
    assert matches[0].matched_term == "A123456"

    # The NIF embedded in a longer alphanumeric code must not match.
    miss = _Doc(2, "Altres", "Expedient A1234567 sense relació")
    assert _match_document(miss, [customer], []) == []


@pytest.mark.unit
def test_customer_without_nif_does_not_raise_and_matches_on_name():
    """A customer object whose ``nif`` is missing/None still matches on name."""
    doc = _Doc(1, "Adjudicació", "Acme Corp guanya el concurs")
    assert len(_match_document(doc, [_customer("c1", "Acme Corp", nif=None)], [])) == 1


@pytest.mark.unit
def test_project_name_match_overrides_bare_customer_match():
    """A project-name hit yields a single project-level match for the key."""
    doc = _Doc(1, "Obres", "Acme Corp lidera el projecte Bridge Renewal")
    customers = [_customer("c1", "Acme Corp")]
    projects = [_project("p1", "c1", "Bridge Renewal")]
    matches = _match_document(doc, customers, projects)
    assert len(matches) == 1
    assert matches[0].project_id == "p1"
    assert matches[0].matched_term == "Bridge Renewal"
