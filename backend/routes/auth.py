from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
import uuid
from datetime import datetime

from auth import (
    create_access_token,
    get_current_user,
    get_db,
    serialize_user,
    verify_password,
    bearer_scheme,
    decode_access_token,
)
import models
import schemas
from services.audit import log_audit_event

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_client_ip(request: Request) -> str | None:
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/login", response_model=schemas.TokenOut)
def login(request: Request, payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    ip_address = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    user = db.query(models.User).filter(models.User.login_id == payload.login_id).first()
    
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        # Create failed session record
        failed_session = models.SessionRecord(
            user_id=user.id if user else None,
            login_time=datetime.utcnow(),
            logout_time=datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent,
            access_status="Failed",
            session_token_id=None,
            is_active=False,
        )
        db.add(failed_session)
        db.commit()

        # Log audit event
        log_audit_event(
            db=db,
            user_id=user.id if user else None,
            action="Login Failure",
            entity_type="User",
            entity_id=str(user.id) if user else None,
            new_value=f"Attempted Login ID: {payload.login_id}",
            ip_address=ip_address,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login ID or password",
        )

    # Successful login: create active session
    session_token_id = str(uuid.uuid4())
    session_record = models.SessionRecord(
        user_id=user.id,
        login_time=datetime.utcnow(),
        ip_address=ip_address,
        user_agent=user_agent,
        access_status="Success",
        session_token_id=session_token_id,
        is_active=True,
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)

    # Log audit event
    log_audit_event(
        db=db,
        user_id=user.id,
        action="Login Success",
        entity_type="User",
        entity_id=str(user.id),
        new_value=user.login_id,
        ip_address=ip_address,
    )

    return {
        "access_token": create_access_token(user, session_token_id),
        "token_type": "bearer",
        "user": serialize_user(db, user),
    }


@router.post("/logout")
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    ip_address = get_client_ip(request)

    # Try to find active session by sid in the token claims
    try:
        payload = decode_access_token(credentials.credentials)
        sid = payload.get("sid")
        if sid:
            session_record = db.query(models.SessionRecord).filter(
                models.SessionRecord.session_token_id == sid,
                models.SessionRecord.is_active == True,
            ).first()
            if session_record:
                session_record.is_active = False
                session_record.logout_time = datetime.utcnow()
                db.commit()
    except Exception:
        pass

    # Log audit event
    log_audit_event(
        db=db,
        user_id=current_user.id,
        action="Logout",
        entity_type="User",
        entity_id=str(current_user.id),
        new_value=current_user.login_id,
        ip_address=ip_address,
    )

    return {"message": f"Logged out {current_user.login_id}"}


@router.get("/me", response_model=schemas.UserOut)
def me(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_user(db, current_user)

