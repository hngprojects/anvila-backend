from app.worker.celery_app import celery_app

PURGE_AFTER_DAYS = 30


@celery_app.task
def purge_soft_deleted() -> dict:
    # Calculate the cutoff: now() - 30 days
    # cutoff = datetime.now(timezone.utc) - timedelta(days=PURGE_AFTER_DAYS)
    #
    # Open a sync DB session (Celery tasks are synchronous).
    #
    # Step 1: Delete conversation_messages where:
    #   session_id IN (
    #     SELECT id FROM chat_sessions WHERE deleted_at < cutoff
    #   )
    #
    # Step 2: Delete chat_sessions where deleted_at < cutoff
    #
    # Step 3: Delete personas where deleted_at < cutoff
    #
    # Commit after each step or once at the end — your choice,
    # but if step 3 fails after step 1 and 2 committed, that is acceptable
    # (messages and sessions are already cleaned, persona will be caught
    # on the next run).
    #
    # Log the count of deleted records per table.
    #
    # Return {
    #   "messages_deleted": int,
    #   "sessions_deleted": int,
    #   "personas_deleted": int,
    # }
    raise NotImplementedError
