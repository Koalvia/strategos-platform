"""SQLAlchemy models for the BOPA domain.

These persist what the BOPA integration client fetches so it can be queried
later without hitting the upstream Azure Functions API on every request. Only
text, metadata and constructed reference URLs are stored — never the multi-MB
per-document / sumari PDFs themselves (see the epic's storage decision).

A numbered BOPA issue is immutable once published, so a :class:`BopaBulletin`
row is written once and never re-synced; the ``(year, num)`` unique constraint
enforces that at the database level and the ``(bulletin_id, document_name)``
constraint does the same per document.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class BopaBulletin(Base):
    """One synced BOPA bulletin issue (a numbered edition for a given year)."""

    __tablename__ = "bopa_bulletins"
    __table_args__ = (UniqueConstraint("year", "num", name="uq_bopa_bulletin_year_num"),)

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    num = Column(Integer, nullable=False)
    is_extra = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime, nullable=False)
    # The API's own ``totalCount`` for the issue; can be a few higher than the
    # number of documents actually persisted (a known upstream gap, see #48).
    total_document_count = Column(Integer, nullable=False)
    sumari_pdf_url = Column(String, nullable=False)
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())

    documents = relationship(
        "BopaDocument",
        back_populates="bulletin",
        cascade="all, delete-orphan",
    )

    @property
    def document_count(self) -> int:
        """Number of documents actually persisted for this bulletin."""
        return len(self.documents)


class BopaDocument(Base):
    """One document belonging to a synced :class:`BopaBulletin`."""

    __tablename__ = "bopa_documents"
    __table_args__ = (
        UniqueConstraint(
            "bulletin_id", "document_name", name="uq_bopa_document_bulletin_name"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    bulletin_id = Column(
        Integer,
        ForeignKey("bopa_bulletins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    organisme = Column(String, nullable=False)
    organisme_pare = Column(String, nullable=False)
    tema = Column(String, nullable=False)
    tema_pare = Column(String, nullable=False)
    title = Column(String, nullable=False)
    article_date = Column(DateTime, nullable=False)
    source_url = Column(String, nullable=False)
    pdf_url = Column(String, nullable=False)
    # Populated only for HTML documents (``file_type`` in ``html``/``htmlCopy``);
    # NULL otherwise (see BopaService.sync_latest).
    html_content = Column(Text, nullable=True)
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())

    bulletin = relationship("BopaBulletin", back_populates="documents")
