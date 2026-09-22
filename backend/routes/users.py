from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import json

from database import SessionLocal
from auth import require_permissions, serialize_user
import crud
import schemas
import models
from services.audit import set_audit_data, log_audit_event
from routes.auth import get_client_ip

router = APIRouter(prefix="/users", tags=["Users"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=schemas.UserOut)
def add_user(
    request: Request,
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("users:manage")),
):
    created_user = crud.create_user(db, user)
    set_audit_data(
        request=request,
        action="User Created",
        entity_type="User",
        entity_id=created_user["id"],
        old_value=None,
        new_value=json.dumps(created_user),
    )
    return created_user


@router.get("/", response_model=list[schemas.UserOut])
def get_users(
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("users:view")),
):
    return crud.get_users(db)


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(
    request: Request,
    user_id: int,
    user: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("users:manage")),
):
    old_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not old_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    old_user_dict = serialize_user(db, old_user)

    updated_user = crud.update_user(db, user_id, user)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    set_audit_data(
        request=request,
        action="User Updated",
        entity_type="User",
        entity_id=user_id,
        old_value=json.dumps(old_user_dict),
        new_value=json.dumps(updated_user),
    )

    # Check for role changes
    old_roles = old_user_dict.get("roles", [])
    new_roles = updated_user.get("roles", [])
    if set(old_roles) != set(new_roles):
        ip = get_client_ip(request)
        for r in old_roles:
            if r not in new_roles:
                log_audit_event(
                    db=db,
                    user_id=current_user.id,
                    action="Role Removed",
                    entity_type="System",
                    entity_id=str(user_id),
                    old_value=r,
                    ip_address=ip,
                )
        for r in new_roles:
            if r not in old_roles:
                log_audit_event(
                    db=db,
                    user_id=current_user.id,
                    action="Role Assigned",
                    entity_type="System",
                    entity_id=str(user_id),
                    new_value=r,
                    ip_address=ip,
                )
        log_audit_event(
            db=db,
            user_id=current_user.id,
            action="Permission Changed",
            entity_type="System",
            entity_id=str(user_id),
            old_value=json.dumps(old_user_dict.get("permissions", [])),
            new_value=json.dumps(updated_user.get("permissions", [])),
            ip_address=ip,
        )

    return updated_user


@router.delete("/{user_id}", response_model=schemas.UserOut)
def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("users:manage")),
):
    old_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not old_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    old_user_dict = serialize_user(db, old_user)

    deleted_user = crud.delete_user(db, user_id)
    if not deleted_user:
        raise HTTPException(status_code=404, detail="User not found")

    set_audit_data(
        request=request,
        action="User Deleted",
        entity_type="User",
        entity_id=user_id,
        old_value=json.dumps(old_user_dict),
        new_value=None,
    )

    # Log role removals for System audit
    ip = get_client_ip(request)
    for r in old_user_dict.get("roles", []):
        log_audit_event(
            db=db,
            user_id=current_user.id,
            action="Role Removed",
            entity_type="System",
            entity_id=str(user_id),
            old_value=r,
            ip_address=ip,
        )

    return deleted_user
