from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import json

from database import SessionLocal
from auth import require_permissions
import crud
import schemas
import models
from services.audit import set_audit_data

router = APIRouter(prefix="/hotlist", tags=["Hotlist"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def serialize_hotlist(entry) -> dict:
    if not entry:
        return {}
    if isinstance(entry, dict):
        return {
            "id": entry.get("id"),
            "plate_number": entry.get("plate_number"),
            "category_id": entry.get("category_id"),
        }
    return {
        "id": entry.id,
        "plate_number": entry.plate_number,
        "category_id": entry.category_id,
    }

@router.post("/", response_model=schemas.HotlistOut)
def add_hotlist_entry(
    request: Request,
    entry: schemas.HotlistCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("hotlist:manage")),
):
    # Check if plate already exists
    existing = crud.get_hotlist_by_plate(db, entry.plate_number)
    if existing:
        raise HTTPException(status_code=400, detail="Plate already in hotlist")
    
    created_entry = crud.create_hotlist_entry(db, entry)
    set_audit_data(
        request=request,
        action="Record Added",
        entity_type="Hotlist",
        entity_id=created_entry["id"],
        old_value=None,
        new_value=json.dumps(serialize_hotlist(created_entry)),
    )
    return created_entry

@router.get("/", response_model=list[schemas.HotlistOut])
def get_hotlist(
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("hotlist:view")),
):
    return crud.get_hotlist(db)

@router.put("/{entry_id}", response_model=schemas.HotlistOut)
def update_hotlist_entry(
    request: Request,
    entry_id: int,
    entry_data: schemas.HotlistCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("hotlist:manage")),
):
    entry = db.query(models.Hotlist).filter(models.Hotlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    old_entry_dict = serialize_hotlist(entry)

    # Check if new plate number already exists on a different entry
    if entry_data.plate_number != entry.plate_number:
        existing = crud.get_hotlist_by_plate(db, entry_data.plate_number)
        if existing:
            raise HTTPException(status_code=400, detail="Plate already in hotlist")

    # Update entry
    entry.plate_number = entry_data.plate_number
    entry.category_id = entry_data.category_id
    db.commit()

    updated = crud.get_hotlist_by_id(db, entry_id)
    set_audit_data(
        request=request,
        action="Record Updated",
        entity_type="Hotlist",
        entity_id=entry_id,
        old_value=json.dumps(old_entry_dict),
        new_value=json.dumps(serialize_hotlist(updated)),
    )
    return updated

@router.delete("/{entry_id}", response_model=schemas.HotlistOut)
def delete_hotlist_entry(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("hotlist:manage")),
):
    # Get the entry first to return it
    entry = crud.get_hotlist_by_id(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
        
    crud.delete_hotlist_entry(db, entry_id)
    set_audit_data(
        request=request,
        action="Record Deleted",
        entity_type="Hotlist",
        entity_id=entry_id,
        old_value=json.dumps(serialize_hotlist(entry)),
        new_value=None,
    )
    return entry

