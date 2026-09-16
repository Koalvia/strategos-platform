"""BOPA transport DTOs.

These Pydantic v2 models mirror the JSON returned by the BOPA
(*Butlletí Oficial del Principat d'Andorra*) Azure Functions API. They are
transport objects for the integration layer, not the shapes Strategos exposes to
its own frontend, and they validate directly against the raw API JSON via
``validation_alias`` on each field.

Three upstream quirks are normalised here so callers never see them:

* ``isExtra`` is a JSON boolean on the bulletin-listing endpoint but the string
  ``"True"``/``"False"`` on the documents endpoint — both collapse to a real
  ``bool`` (see :func:`_normalize_bool`).
* ``sumari`` (a document's title) is percent-encoded UTF-8 (``%c3%ba`` -> ``ú``)
  — it is decoded with :func:`urllib.parse.unquote` before being stored.
* the classification labels (``organisme``, ``organismePare``, ``tema``,
  ``temaPare``) are occasionally ``null`` for a document. Bulletin 89/2026
  shipped one such document; with the labels declared as required strings the
  whole issue failed validation, and every later issue stayed out of the
  platform for six weeks. They are coalesced to ``""`` instead.
"""

import re
from datetime import datetime
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ``numBOPA`` on the listing endpoint is a human string like ``"Núm. 77 any
# 2026"``; the endpoint does not return the year as its own field, so it is
# parsed out of that string.
_YEAR_RE = re.compile(r"any (\d{4})")


def _normalize_bool(value: object) -> object:
    """Collapse BOPA's bool/string ``isExtra`` representations to a real ``bool``.

    The listing endpoint sends a JSON boolean; the documents endpoint sends the
    string ``"True"``/``"False"``. Anything already a ``bool`` passes through;
    a string is compared case-insensitively against ``"true"``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() == "true"
    return value


class BopaBulletinListItem(BaseModel):
    """One bulletin issue from ``GET /api/GetMonthButlletins``.

    ``year`` has no dedicated field upstream — it is parsed out of the
    ``numBOPA`` display string (e.g. ``"Núm. 77 any 2026"``) with a regex.
    """

    model_config = ConfigDict(populate_by_name=True)

    num: int = Field(validation_alias="num")
    year: int = Field(validation_alias="numBOPA")
    is_extra: bool = Field(validation_alias="isExtra")
    published_at: datetime = Field(validation_alias="dataPublicacio")

    @field_validator("year", mode="before")
    @classmethod
    def _parse_year(cls, value: object) -> object:
        """Extract the 4-digit year from the ``numBOPA`` display string."""
        if isinstance(value, str):
            match = _YEAR_RE.search(value)
            if match:
                return int(match.group(1))
        return value

    @field_validator("is_extra", mode="before")
    @classmethod
    def _coerce_is_extra(cls, value: object) -> object:
        return _normalize_bool(value)


class BopaDocument(BaseModel):
    """One document of a bulletin issue (from ``GET /api/GetDocumentsByBOPA``).

    The raw payload nests these fields under each ``paginatedDocuments[].document``
    object; :class:`BopaDocumentsPage` unwraps that so this model validates
    against the inner ``document`` dict directly.
    """

    model_config = ConfigDict(populate_by_name=True)

    storage_name: str = Field(validation_alias="metadata_storage_name")
    storage_size: int = Field(validation_alias="metadata_storage_size")
    source_url: str = Field(validation_alias="metadata_storage_path")
    # Classification labels: ``null`` upstream (or a missing key) becomes ``""``
    # so one such document cannot fail validation for its whole bulletin.
    organisme: str = Field("", validation_alias="organisme")
    organisme_pare: str = Field("", validation_alias="organismePare")
    tema: str = Field("", validation_alias="tema")
    tema_pare: str = Field("", validation_alias="temaPare")
    file_type: str = Field(validation_alias="fileType")
    published_at: datetime = Field(validation_alias="dataPublicacioButlleti")
    article_date: datetime = Field(validation_alias="dataArticle")
    is_extra: bool = Field(validation_alias="isExtra")
    num: int = Field(validation_alias="numButlleti")
    year: int = Field(validation_alias="anyButlleti")
    title: str = Field(validation_alias="sumari")
    document_name: str = Field(validation_alias="nomDocument")

    @field_validator("is_extra", mode="before")
    @classmethod
    def _coerce_is_extra(cls, value: object) -> object:
        return _normalize_bool(value)

    @field_validator(
        "organisme", "organisme_pare", "tema", "tema_pare", mode="before"
    )
    @classmethod
    def _coalesce_null_label(cls, value: object) -> object:
        """Turn a ``null`` classification label into ``""`` (see module docstring)."""
        return "" if value is None else value

    @field_validator("title", mode="before")
    @classmethod
    def _decode_title(cls, value: object) -> object:
        """Percent-decode the UTF-8 ``sumari`` (``%c3%ba`` -> ``ú``)."""
        if isinstance(value, str):
            return unquote(value)
        return value


class BopaDocumentsPage(BaseModel):
    """One page of a bulletin issue's documents (``GET /api/GetDocumentsByBOPA``).

    ``total_count`` is the API's own count of matching documents; it can be a few
    higher than ``len(documents)`` actually returned (a known upstream gap) — the
    live client logs a warning when they differ rather than treating it as an
    error.
    """

    model_config = ConfigDict(populate_by_name=True)

    total_count: int = Field(validation_alias="totalCount")
    documents: list[BopaDocument] = Field(validation_alias="paginatedDocuments")

    @field_validator("documents", mode="before")
    @classmethod
    def _unwrap_documents(cls, value: object) -> object:
        """Lift each ``paginatedDocuments[].document`` object up to the list.

        The endpoint wraps every document in a ``{score, highlights, document}``
        envelope; only the inner ``document`` carries the fields we model.
        """
        if isinstance(value, list):
            return [
                entry.get("document", entry) if isinstance(entry, dict) else entry
                for entry in value
            ]
        return value
