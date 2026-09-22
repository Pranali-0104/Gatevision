from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, time
from typing import Optional

from database import SessionLocal
import models
from auth import require_permissions

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_audit_logs(
    user_id: Optional[int] = None,
    action: Optional[str] = "",
    search: Optional[str] = "",
    entity_type: Optional[str] = "",
    from_date: Optional[str] = "",
    to_date: Optional[str] = "",
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_permissions("audit_logs:view")),
):
    query = db.query(models.AuditLog, models.User).outerjoin(
        models.User, models.AuditLog.user_id == models.User.id
    )

    if user_id is not None:
        query = query.filter(models.AuditLog.user_id == user_id)
        
    if action:
        query = query.filter(models.AuditLog.action.contains(action))
        
    if search:
        query = query.filter(
            (models.AuditLog.action.contains(search)) |
            (models.User.login_id.contains(search))
        )

    if entity_type:
        query = query.filter(models.AuditLog.entity_type == entity_type)
        
    if from_date:
        start_date = datetime.strptime(from_date, "%Y-%m-%d")
        query = query.filter(models.AuditLog.timestamp >= start_date)
        
    if to_date:
        end_date = datetime.combine(
            datetime.strptime(to_date, "%Y-%m-%d").date(),
            time.max
        )
        query = query.filter(models.AuditLog.timestamp <= end_date)

    total = query.count()
    offset = (page - 1) * limit
    results = query.order_by(models.AuditLog.timestamp.desc()).offset(offset).limit(limit).all()

    logs_out = []
    for log, user in results:
        logs_out.append({
            "id": log.id,
            "user_id": log.user_id,
            "user_login_id": user.login_id if user else (f"User ID: {log.user_id}" if log.user_id else "System"),
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": logs_out
    }


@router.get("/{log_id}")
def get_audit_log_by_id(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_permissions("audit_logs:view")),
):
    log = db.query(models.AuditLog).filter(models.AuditLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Audit log not found")

    user = db.query(models.User).filter(models.User.id == log.user_id).first()
    return {
        "id": log.id,
        "user_id": log.user_id,
        "user_login_id": user.login_id if user else (f"User ID: {log.user_id}" if log.user_id else "System"),
        "action": log.action,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "old_value": log.old_value,
        "new_value": log.new_value,
        "ip_address": log.ip_address,
        "timestamp": log.timestamp
    }
