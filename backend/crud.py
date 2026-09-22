from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import models
import schemas
from auth import ROLE_VIEWER, assign_roles, hash_password, serialize_user

# ---------- VEHICLE EVENTS ----------
def create_vehicle_event(db: Session, event_data: dict):
    db_event = models.VehicleEvent(**event_data)
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


def get_vehicle_events(db: Session):
    return db.query(models.VehicleEvent).order_by(models.VehicleEvent.timestamp.desc()).all()

def search_vehicle_events(db: Session, plate=None, category=None):
    query = db.query(models.VehicleEvent)

    if plate:
        query = query.filter(models.VehicleEvent.plate_text.contains(plate))

    if category:
        query = query.filter(models.VehicleEvent.category == category)

    return query.order_by(models.VehicleEvent.timestamp.desc()).all()


# ---------- USERS ----------
def create_user(db: Session, user: schemas.UserCreate):
    data = user.dict()
    password = data.pop("password", None) or "ChangeMe123!"
    roles = data.pop("roles", None) or [ROLE_VIEWER]
    db_user = models.User(**data, password_hash=hash_password(password), is_active=True)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    assign_roles(db, db_user, roles)
    db.refresh(db_user)
    return serialize_user(db, db_user)


def get_users(db: Session):
    return [serialize_user(db, user) for user in db.query(models.User).all()]


def update_user(db: Session, user_id: int, user_data: schemas.UserUpdate):
    user = db.query(models.User).get(user_id)
    if user:
        data = user_data.dict()
        password = data.pop("password", None)
        roles = data.pop("roles", None)
        for key, value in data.items():
            setattr(user, key, value)
        if password:
            user.password_hash = hash_password(password)
        db.commit()
        if roles is not None:
            assign_roles(db, user, roles)
        db.refresh(user)
        return serialize_user(db, user)
    return None


def delete_user(db: Session, user_id: int):
    user = db.query(models.User).get(user_id)
    if user:
        user_out = serialize_user(db, user)
        db.query(models.UserRole).filter(models.UserRole.user_id == user_id).delete()
        db.delete(user)
        db.commit()
        return user_out
    return None

# ---------- CATEGORIES ----------
def create_category(db: Session, category: schemas.CategoryCreate):
    db_category = models.Category(**category.dict())
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

def get_categories(db: Session):
    return db.query(models.Category).all()

def delete_category(db: Session, category_id: int):
    category = db.query(models.Category).get(category_id)
    if category:
        db.delete(category)
        db.commit()
    return category

# ---------- WATCHLIST / HOTLIST ----------
def create_hotlist_entry(db: Session, entry: schemas.HotlistCreate):
    db_entry = models.Hotlist(**entry.dict())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return get_hotlist_by_id(db, db_entry.id)

def get_hotlist(db: Session):
    results = db.query(models.Hotlist, models.Category).outerjoin(
        models.Category, models.Hotlist.category_id == models.Category.id
    ).all()
    
    hotlist_out = []
    for hotlist, category in results:
        hotlist_dict = {
            "id": hotlist.id,
            "plate_number": hotlist.plate_number,
            "category_id": hotlist.category_id,
            "created_at": hotlist.created_at,
            "created_by": hotlist.created_by,
            "category_name": category.name if category else "Unknown",
            "category_icon": category.icon if category else "",
            "category_color": category.color if category else "#gray",
            "has_sound_alert": category.has_sound_alert if category else False,
            "has_visual_alert": category.has_visual_alert if category else False,
        }
        hotlist_out.append(hotlist_dict)
    return hotlist_out

def get_hotlist_by_id(db: Session, entry_id: int):
    result = db.query(models.Hotlist, models.Category).outerjoin(
        models.Category, models.Hotlist.category_id == models.Category.id
    ).filter(models.Hotlist.id == entry_id).first()
    
    if result:
        hotlist, category = result
        return {
            "id": hotlist.id,
            "plate_number": hotlist.plate_number,
            "category_id": hotlist.category_id,
            "created_at": hotlist.created_at,
            "created_by": hotlist.created_by,
            "category_name": category.name if category else "Unknown",
            "category_icon": category.icon if category else "",
            "category_color": category.color if category else "#gray",
            "has_sound_alert": category.has_sound_alert if category else False,
            "has_visual_alert": category.has_visual_alert if category else False,
        }
    return None

def delete_hotlist_entry(db: Session, entry_id: int):
    entry = db.query(models.Hotlist).get(entry_id)
    if entry:
        db.delete(entry)
        db.commit()
    return entry

def get_hotlist_by_plate(db: Session, plate: str):
    result = db.query(models.Hotlist, models.Category).outerjoin(
        models.Category, models.Hotlist.category_id == models.Category.id
    ).filter(models.Hotlist.plate_number == plate).first()
    
    if result:
        hotlist, category = result
        return {
            "id": hotlist.id,
            "plate_number": hotlist.plate_number,
            "category_id": hotlist.category_id,
            "created_at": hotlist.created_at,
            "created_by": hotlist.created_by,
            "category_name": category.name if category else "Unknown",
            "category_icon": category.icon if category else "",
            "category_color": category.color if category else "#gray",
            "category_code": category.code if category else "unknown",
            "has_sound_alert": category.has_sound_alert if category else False,
            "has_visual_alert": category.has_visual_alert if category else False
        }
    return None
