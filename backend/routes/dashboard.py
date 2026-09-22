from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
from auth import get_current_user
import models
from datetime import datetime

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # UTC day boundary (detections logged today in UTC)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_detections = db.query(models.VehicleEvent).filter(models.VehicleEvent.timestamp >= today_start).count()
    
    vip_count = db.query(models.VehicleEvent).filter(
        (models.VehicleEvent.category_code == 'vip') | 
        (models.VehicleEvent.category_name == 'VIP') | 
        (models.VehicleEvent.category == 'VIP')
    ).count()
    
    # Matches both "stolen" and "blacklist" configurations for robust categorization
    blacklist_count = db.query(models.VehicleEvent).filter(
        (models.VehicleEvent.category_code.in_(['stolen', 'blacklist'])) | 
        (models.VehicleEvent.category_name.in_(['Stolen', 'Blacklist'])) | 
        (models.VehicleEvent.category.in_(['Stolen', 'Blacklist']))
    ).count()
    
    total_records = db.query(models.VehicleEvent).count()
    
    return {
        "today_detections": today_detections,
        "vip_count": vip_count,
        "blacklist_count": blacklist_count,
        "total_records": total_records
    }
