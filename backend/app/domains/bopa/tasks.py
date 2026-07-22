"""Celery tasks for the BOPA domain."""
from app import logger
from app.celery_app import celery
from app.core.dependencies import get_bopa_client, get_business_central_client
from app.db.session import SessionLocal
from app.domains.alerts.service import AlertsService
from app.domains.customers.service import CustomersService

from .models import BopaAnalysisLog, BopaBulletin, BopaDocument, BopaMatch
from .service import BopaService


def _searchable_text(doc: BopaDocument) -> str:
    """Lowercased title + body used for substring matching against a document."""
    return f"{doc.title} {doc.html_content or ''}".lower()


def _match_document(doc, customers, projects) -> list[BopaMatch]:
    """Build the customer/project matches for a single document.

    Matches on ``customer.name`` and ``project.name`` (NIF is intentionally not
    considered here — the global analyzer never matched on it). Deduplicates on
    ``(customer_id, document_id)`` — the ``uq_bopa_match_customer_doc`` constraint
    allows only one match per customer per document — and lets a project-level
    match override a bare customer-name match for the same key.
    """
    searchable_text = _searchable_text(doc)
    doc_matches: dict[tuple[str, int], BopaMatch] = {}

    # Check for customer name matches
    for customer in customers:
        if customer.name and customer.name.lower() in searchable_text:
            key = (customer.id, doc.id)
            doc_matches.setdefault(
                key,
                BopaMatch(
                    customer_id=customer.id,
                    document_id=doc.id,
                    matched_term=customer.name,
                ),
            )

    # Check for project name matches (override any bare customer match)
    for project in projects:
        if project.name and project.name.lower() in searchable_text:
            key = (project.customer_id, doc.id)
            doc_matches[key] = BopaMatch(
                customer_id=project.customer_id,
                project_id=project.id,
                document_id=doc.id,
                matched_term=project.name,
            )

    return list(doc_matches.values())


@celery.task(name="bopa.sync_daily")
def sync_bopa_daily():
    """Sync the latest BOPA bulletins once a day (Celery Beat entry).

    Runs outside FastAPI's request scope, so the DB session and BOPA client are
    built directly here rather than injected via ``Depends``.
    """
    db = SessionLocal()
    try:
        service = BopaService(db=db, bopa_client=get_bopa_client())
        result = service.sync_latest()
        logger.info(
            f"BOPA sync: {result.bulletins_synced} bulletins, "
            f"{result.documents_synced} documents "
            f"({result.documents_failed} failed)"
        )
    finally:
        db.close()

@celery.task(name="bopa.analyze_matches")
def analyze_bopa_matches() -> int:
    """Analyze unanalyzed BOPA bulletins against customers and projects.

    Stores matches in the BopaMatch table and records the analysis in BopaAnalysisLog
    to prevent duplicate processing. Runs outside FastAPI's request scope.

    Returns the number of new matches created (0 when there is nothing new to
    analyze), so on-demand callers (e.g. the ``POST /bopa/scan`` button) can report
    how many were found.
    """
    db = SessionLocal()
    try:
        # Find bulletins that have not been analyzed yet
        unanalyzed_bulletins = (
            db.query(BopaBulletin)
            .outerjoin(BopaAnalysisLog, BopaBulletin.id == BopaAnalysisLog.bulletin_id)
            .filter(BopaAnalysisLog.id.is_(None))
            .all()
        )

        if not unanalyzed_bulletins:
            logger.info("BOPA analysis: No new bulletins to analyze.")
            return 0

        # Fetch customers and projects from Business Central
        bc_client = get_business_central_client()

        # Note: Assuming standard methods on bc_client based on previous implementation
        customers = bc_client.get_customers()
        projects = bc_client.get_projects()

        total_matches = 0

        for bulletin in unanalyzed_bulletins:
            matches_to_insert = []

            # Fetch all documents for this specific bulletin
            documents = (
                db.query(BopaDocument)
                .filter(BopaDocument.bulletin_id == bulletin.id)
                .all()
            )

            for doc in documents:
                matches_to_insert.extend(_match_document(doc, customers, projects))

            # Save matches and raise one alert per match. We add + flush (rather
            # than bulk_save_objects) so each match gets its ``id`` assigned,
            # which AlertsService.create_for_match needs for the alert's FK.
            if matches_to_insert:
                alerts_service = AlertsService(db)
                for match in matches_to_insert:
                    db.add(match)
                    db.flush()
                    alerts_service.create_for_match(match)
                total_matches += len(matches_to_insert)

            # Mark bulletin as analyzed
            analysis_log = BopaAnalysisLog(
                bulletin_id=bulletin.id,
                matches_found=len(matches_to_insert)
            )
            db.add(analysis_log)

            # Commit per bulletin to save progress in case of an unexpected crash
            db.commit()

        logger.info(
            f"BOPA analysis complete: Processed {len(unanalyzed_bulletins)} bulletins, "
            f"found {total_matches} new matches."
        )
        return total_matches

    except Exception as e:
        db.rollback()
        logger.error(f"BOPA analysis failed: {str(e)}")
        raise e
    finally:
        db.close()


@celery.task(name="bopa.analyze_matches_for_customer")
def analyze_bopa_matches_for_customer(customer_id: str) -> int:
    """Analyze every stored BOPA document against a single customer.

    The on-demand, customer-scoped counterpart to :func:`analyze_bopa_matches`,
    triggered by the "Iniciar Escaneo" button on a customer detail page. It
    differs from the global analyzer on purpose:

    * It does **not** read or write :class:`BopaAnalysisLog`. That log is a
      *per-bulletin* "already analyzed" marker; writing it from a single-customer
      run would permanently hide the bulletin from every other customer.
    * It scans **all** documents (not just unanalyzed bulletins), skipping the
      ones already matched for this customer, so a customer added after a bulletin
      was globally analyzed still gets matched.
    * It matches on the customer's name, NIF **and** project names (the customer
      search on the same screen matches these three; the global analyzer ignores
      NIF).

    Idempotent — re-running only adds newly-matched documents. Returns the number
    of new matches created. Raises 404 (via ``CustomersService``) if the customer
    does not exist.
    """
    db = SessionLocal()
    try:
        bc_client = get_business_central_client()
        # Resolves name + NIF, or raises 404 if the customer id is unknown.
        customer = CustomersService(db, bc_client).get_customer(customer_id)
        customer_projects = [
            p for p in bc_client.get_projects() if p.customer_id == customer_id
        ]
        nif = (customer.nif or "").strip()

        # Documents already matched for this customer — skip them so re-scans stay
        # idempotent and we never trip uq_bopa_match_customer_doc.
        already_matched = {
            row[0]
            for row in db.query(BopaMatch.document_id).filter(
                BopaMatch.customer_id == customer_id
            )
        }

        alerts_service = AlertsService(db)
        total_matches = 0

        for doc in db.query(BopaDocument).all():
            if doc.id in already_matched:
                continue

            # Name + project matches (CustomerResponse exposes .id/.name, so it
            # slots into _match_document exactly like a BCCustomer).
            doc_matches = _match_document(doc, [customer], customer_projects)

            # NIF fallback: only when nothing else matched this document, to avoid
            # a second row for the same (customer, document) key.
            if not doc_matches and nif and nif.lower() in _searchable_text(doc):
                doc_matches = [
                    BopaMatch(
                        customer_id=customer_id,
                        document_id=doc.id,
                        matched_term=nif,
                    )
                ]

            for match in doc_matches:
                db.add(match)
                db.flush()
                alerts_service.create_for_match(match)
                total_matches += 1

        db.commit()
        logger.info(
            f"BOPA customer scan ({customer_id}): {total_matches} new matches."
        )
        return total_matches

    except Exception as e:
        db.rollback()
        logger.error(f"BOPA customer scan failed for {customer_id}: {str(e)}")
        raise e
    finally:
        db.close()
