from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import json

from database import SessionLocal
from auth import require_permissions
import crud
import schemas
import models
from services.audit import set_audit_data

router = APIRouter(prefix="/categories", tags=["Categories"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def serialize_category(category: models.Category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "icon": category.icon,
        "color": category.color,
        "description": category.description,
        "has_sound_alert": bool(category.has_sound_alert),
        "has_visual_alert": bool(category.has_visual_alert),
    }

@router.post("/", response_model=schemas.CategoryOut)
def add_category(
    request: Request,
    category: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("categories:manage")),
):
    created_cat = crud.create_category(db, category)
    set_audit_data(
        request=request,
        action="Category Created",
        entity_type="Category",
        entity_id=created_cat.id,
        old_value=None,
        new_value=json.dumps(serialize_category(created_cat)),
    )
    return created_cat

@router.get("/", response_model=list[schemas.CategoryOut])
def get_categories(
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("categories:view")),
):
    return crud.get_categories(db)

@router.put("/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    request: Request,
    category_id: int,
    category_data: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("categories:manage")),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    old_cat_dict = serialize_category(category)

    # Apply updates
    data = category_data.dict()
    for key, val in data.items():
        setattr(category, key, val)
    db.commit()
    db.refresh(category)

    new_cat_dict = serialize_category(category)
    set_audit_data(
        request=request,
        action="Category Updated",
        entity_type="Category",
        entity_id=category_id,
        old_value=json.dumps(old_cat_dict),
        new_value=json.dumps(new_cat_dict),
    )
    return category

@router.delete("/{category_id}", response_model=schemas.CategoryOut)
def delete_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("categories:manage")),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
        
    old_cat_dict = serialize_category(category)

    deleted_category = crud.delete_category(db, category_id)
    if not deleted_category:
        raise HTTPException(status_code=404, detail="Category not found")

    set_audit_data(
        request=request,
        action="Category Deleted",
        entity_type="Category",
        entity_id=category_id,
        old_value=json.dumps(old_cat_dict),
        new_value=None,
    )
    return deleted_category

