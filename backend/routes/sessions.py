from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, time
from typing import Optional

from database import SessionLocal
import models
from auth import (
    require_permissions,
    get_current_user,
    get_user_roles,
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_session_access(current_user: models.User, target_user_id: int | None, db: Session):
    """
    Ensure the current user has permission to view the target user's sessions.
    Operator can only view their own. Admins and Super Admins can view all.
    """
    roles = get_user_roles(db, current_user.id)
    is_admin = ROLE_ADMIN in roles or ROLE_SUPER_ADMIN in roles
    
    if not is_admin:
        if target_user_id is None or target_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own sessions"
            )


@router.get("/")
def get_sessions(
    user_id: Optional[int] = None,
    ip_address: Optional[str] = "",
    search: Optional[str] = "",
    is_active: Optional[bool] = None,
    from_date: Optional[str] = "",
    to_date: Optional[str] = "",
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_permissions("sessions:view")),
):
    roles = get_user_roles(db, current_user.id)
    is_admin = ROLE_ADMIN in roles or ROLE_SUPER_ADMIN in roles

    # Enforce Operator restrictions
    if not is_admin:
        user_id = current_user.id

    query = db.query(models.SessionRecord, models.User).outerjoin(
        models.User, models.SessionRecord.user_id == models.User.id
    )

    if user_id is not None:
        query = query.filter(models.SessionRecord.user_id == user_id)
        
    if ip_address:
        query = query.filter(models.SessionRecord.ip_address.contains(ip_address))
        
    if search:
        query = query.filter(
            (models.User.login_id.contains(search)) |
            (models.SessionRecord.ip_address.contains(search))
        )

    if is_active is not None:
        query = query.filter(models.SessionRecord.is_active == is_active)
        
    if from_date:
        start_date = datetime.strptime(from_date, "%Y-%m-%d")
        query = query.filter(models.SessionRecord.login_time >= start_date)
        
    if to_date:
        end_date = datetime.combine(
            datetime.strptime(to_date, "%Y-%m-%d").date(),
            time.max
        )
        query = query.filter(models.SessionRecord.login_time <= end_date)

    total = query.count()
    offset = (page - 1) * limit
    results = query.order_by(models.SessionRecord.login_time.desc()).offset(offset).limit(limit).all()

    sessions_out = []
    for session, user in results:
        sessions_out.append({
            "id": session.id,
            "user_id": session.user_id,
            "user_login_id": user.login_id if user else (f"User ID: {session.user_id}" if session.user_id else "Unknown"),
            "login_time": session.login_time,
            "logout_time": session.logout_time,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
            "access_status": session.access_status,
            "is_active": session.is_active
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": sessions_out
    }


@router.get("/{session_id}")
def get_session_by_id(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_permissions("sessions:view")),
):
    session = db.query(models.SessionRecord).filter(models.SessionRecord.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    check_session_access(current_user, session.user_id, db)

    user = db.query(models.User).filter(models.User.id == session.user_id).first()
    return {
        "id": session.id,
        "user_id": session.user_id,
        "user_login_id": user.login_id if user else (f"User ID: {session.user_id}" if session.user_id else "Unknown"),
        "login_time": session.login_time,
        "logout_time": session.logout_time,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "access_status": session.access_status,
        "is_active": session.is_active
    }


@router.get("/user/{user_id}")
def get_sessions_by_user(
    user_id: int,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_permissions("sessions:view")),
):
    check_session_access(current_user, user_id, db)

    query = db.query(models.SessionRecord, models.User).outerjoin(
        models.User, models.SessionRecord.user_id == models.User.id
    ).filter(models.SessionRecord.user_id == user_id)

    total = query.count()
    offset = (page - 1) * limit
    results = query.order_by(models.SessionRecord.login_time.desc()).offset(offset).limit(limit).all()

    sessions_out = []
    for session, user in results:
        sessions_out.append({
            "id": session.id,
            "user_id": session.user_id,
            "user_login_id": user.login_id if user else f"User ID: {session.user_id}",
            "login_time": session.login_time,
            "logout_time": session.logout_time,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
            "access_status": session.access_status,
            "is_active": session.is_active
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": sessions_out
    }
