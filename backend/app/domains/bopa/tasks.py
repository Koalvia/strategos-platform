"""Celery tasks for the BOPA domain."""
from sqlalchemy.exc import IntegrityError

from app import logger
from app.celery_app import celery
from app.core.dependencies import get_bopa_client, get_business_central_client
from app.db.session import SessionLocal
from app.domains.alerts.service import AlertsService
from app.domains.customers.service import CustomersService

from .matching import searchable_text, term_in_text
from .models import BopaAnalysisLog, BopaBulletin, BopaDocument, BopaMatch
from .service import BopaService

# The customer-scoped scan loads documents in batches of this size so a large
# corpus never pulls every unbounded ``html_content`` body into memory at once.
_SCAN_BATCH_SIZE = 500


def _match_document(doc, customers, projects) -> list[BopaMatch]:
    """Build the customer/project matches for a single document.

    A customer matches when its **name** or its **NIF** appears as whole word(s)
    in the document (word-boundary, not a naked substring — see
    ``app.domains.bopa.matching``); the name is the preferred ``matched_term`` and the
    NIF is the fallback label when only the NIF hits. Projects match on their
    name. This word-boundary rule is the guarantee that an alert is genuinely
    about one of our customers: a loose-substring false positive never becomes a
    match, so it is never turned into an alert and never gets a link.

    Deduplicates on ``(customer_id, document_id)`` — the
    ``uq_bopa_match_customer_doc`` constraint allows only one match per customer
    per document — and lets a project-level match override a bare customer match
    for the same key.
    """
    text = searchable_text(doc.title, doc.html_content)
    doc_matches: dict[tuple[str, int], BopaMatch] = {}

    # Customer name/NIF matches (name preferred as the label, NIF as fallback).
    for customer in customers:
        if term_in_text(customer.name, text):
            matched_term = customer.name
        elif term_in_text(getattr(customer, "nif", None), text):
            matched_term = getattr(customer, "nif", None)
        else:
            continue
        key = (customer.id, doc.id)
        doc_matches.setdefault(
            key,
            BopaMatch(
                customer_id=customer.id,
                document_id=doc.id,
                matched_term=matched_term,
            ),
        )

    # Project name matches (override any bare customer match for the same key).
    for project in projects:
        if term_in_text(project.name, text):
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
        raise
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
    * It matches on the customer's name, NIF **and** project names — the same
      whole-word rule the global analyzer now uses (see ``_match_document``).

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

        # Stream the document ids first (cheap — just integers), drop the ones
        # already matched for this customer, and load the full rows in batches.
        # This keeps peak memory bounded even for a corpus of tens of thousands
        # of documents with large ``html_content`` bodies.
        pending_ids = [
            row[0]
            for row in db.query(BopaDocument.id)
            if row[0] not in already_matched
        ]

        for start in range(0, len(pending_ids), _SCAN_BATCH_SIZE):
            batch_ids = pending_ids[start : start + _SCAN_BATCH_SIZE]
            documents = db.query(BopaDocument).filter(
                BopaDocument.id.in_(batch_ids)
            )

            for doc in documents:
                # Name / NIF / project matches. CustomerResponse exposes
                # .id/.name/.nif, so it slots into _match_document exactly like a
                # BCCustomer — NIF matching lives there now (whole-word), so no
                # separate substring fallback is needed here.
                doc_matches = _match_document(doc, [customer], customer_projects)

                for match in doc_matches:
                    # A concurrent scoped scan for the same customer may have
                    # inserted this (customer, document) pair between our
                    # ``already_matched`` snapshot and now. Guard each insert in a
                    # savepoint so a duplicate is skipped (another request already
                    # created it) instead of failing the whole request with an
                    # opaque 500 on uq_bopa_match_customer_doc.
                    try:
                        with db.begin_nested():
                            db.add(match)
                            db.flush()
                    except IntegrityError:
                        continue
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
        raise
    finally:
        db.close()
