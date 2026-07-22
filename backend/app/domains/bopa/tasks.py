"""Celery tasks for the BOPA domain."""
from app import logger
from app.celery_app import celery
from app.core.dependencies import get_bopa_client, get_business_central_client
from app.db.session import SessionLocal
from app.domains.alerts.service import AlertsService

from .models import BopaAnalysisLog, BopaBulletin, BopaDocument, BopaMatch
from .service import BopaService


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
                # Combine title and content for a full-text substring search
                searchable_text = f"{doc.title} {doc.html_content or ''}".lower()

                # Deduplicate on (customer_id, document_id): the unique
                # constraint uq_bopa_match_customer_doc allows only one match per
                # customer per document. A document mentioning both a customer's
                # name and one of that customer's project names would otherwise
                # produce two rows with the same key and raise IntegrityError.
                # A project-level match (project_id set) takes precedence over a
                # bare customer-name match.
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

                matches_to_insert.extend(doc_matches.values())

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
