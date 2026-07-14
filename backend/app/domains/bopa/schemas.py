"""Pydantic v2 schemas for the BOPA domain.

These are the API shapes Strategos exposes to its own frontend, mapped from the
:mod:`app.domains.bopa.models` ORM rows via ``from_attributes``. List responses
deliberately omit ``html_content`` (it can be large) — it is only served on the
per-document detail endpoint.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    """A single BOPA document as shown in a bulletin's document list.

    Excludes ``html_content`` to keep list responses light — use
    :class:`DocumentDetail` (``GET /bopa/documents/{id}``) for the body.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_name: str
    title: str
    organisme: str
    tema: str
    article_date: datetime
    file_type: str
    source_url: str
    pdf_url: str
    # A document carries no year/num of its own — these come from its owning
    # bulletin (via ``BopaDocument.bulletin_year`` / ``bulletin_num``), so search
    # results spanning multiple bulletins stay meaningful ("BOPA núm. 77, 2026").
    bulletin_year: int
    bulletin_num: int


class DocumentDetail(DocumentSummary):
    """A BOPA document including its stored HTML body (``None`` for non-HTML)."""

    html_content: str | None = None


class DocumentSearchPage(BaseModel):
    """A page of search results with the total count of all matching documents."""

    items: list[DocumentSummary]
    total: int


class DocumentFilterOptions(BaseModel):
    """The distinct, sorted values available for each document facet filter."""

    organisme: list[str]
    tema: list[str]
    organisme_pare: list[str]
    tema_pare: list[str]


class BulletinSummary(BaseModel):
    """A BOPA bulletin issue without its documents."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    num: int
    is_extra: bool
    published_at: datetime
    total_document_count: int
    # Documents actually persisted; can be below ``total_document_count`` (see
    # the known upstream gap noted on the model).
    document_count: int
    sumari_pdf_url: str


class BulletinDetail(BulletinSummary):
    """A BOPA bulletin issue together with its documents."""

    documents: list[DocumentSummary] = []


class SyncResult(BaseModel):
    """Outcome of one :meth:`BopaService.sync_latest` run."""

    bulletins_synced: int
    documents_synced: int
    documents_failed: int
