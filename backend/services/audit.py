from datetime import datetime
from fastapi import Request
from sqlalchemy.orm import Session
import models

def set_audit_data(
    request: Request,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    user_id: int | None = None
):
    """
    Store audit details on the request state. The auto-audit middleware
    will capture these values and save them after a successful response.
    """
    request.state.audit_action = action
    request.state.audit_entity_type = entity_type
    request.state.audit_entity_id = str(entity_id) if entity_id is not None else None
    request.state.audit_old_value = old_value
    request.state.audit_new_value = new_value
    if user_id is not None:
        request.state.audit_user_id = user_id

def log_audit_event(
    db: Session,
    user_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    ip_address: str | None = None
) -> models.AuditLog:
    """
    Directly insert an audit log into the database. Use this for events
    outside the request lifecycle or where middleware is not active.
    """
    db_log = models.AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        timestamp=datetime.utcnow()
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log
