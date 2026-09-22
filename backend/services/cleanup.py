import os
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models

logger = logging.getLogger("vehiscan.cleanup")

def run_cleanup(db: Session):
    print("=" * 60)
    print("[Cleanup] Starting automatic 15-day ANPR cleanup job...")
    print("=" * 60)
    
    records_deleted = 0
    images_deleted = 0
    
    try:
        # Cutoff is 15 days ago
        cutoff_date = datetime.utcnow() - timedelta(days=15)
        print(f"[Cleanup] Deleting records and images older than: {cutoff_date.isoformat()}")
        
        # Find all records older than 15 days
        old_records = db.query(models.VehicleEvent).filter(models.VehicleEvent.timestamp < cutoff_date).all()
        total_found = len(old_records)
        print(f"[Cleanup] Found {total_found} expired records to clean up.")
        
        if total_found > 0:
            # Base backend directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            reports_dir = os.path.join(base_dir, "storage", "reports")
            
            for record in old_records:
                # Check if monthly report for this record's month has been generated
                dt = record.timestamp
                month_str = dt.strftime("%B").upper() + str(dt.year)
                monthly_report_path = os.path.join(reports_dir, month_str, f"{month_str}.pdf")
                
                # Only clean up if the monthly report exists (ensures we don't delete records/images before archiving)
                if not os.path.exists(monthly_report_path):
                    continue
                
                # Check if there is an associated filesystem image to delete
                img_url = record.plate_image_url
                if img_url and not img_url.startswith("data:image"):
                    # It's a filesystem path (e.g. storage/2026/06/11/plate_123.jpg)
                    full_path = os.path.join(base_dir, img_url)
                    if os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                            images_deleted += 1
                            
                            # Recursively clean up empty parent directories (day, month, year)
                            parent_dir = os.path.dirname(full_path)
                            for _ in range(3):
                                if os.path.exists(parent_dir) and os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                                    try:
                                        os.rmdir(parent_dir)
                                    except Exception:
                                        break
                                    parent_dir = os.path.dirname(parent_dir)
                                else:
                                    break
                        except Exception as file_err:
                            print(f"[Cleanup Warning] Failed to delete file {full_path}: {file_err}")
                    else:
                        # Continue safely if file is missing
                        pass
                
                # Delete the record
                db.delete(record)
                records_deleted += 1
            
            db.commit()
            
        print(f"[Cleanup] Records Deleted: {records_deleted}")
        print(f"[Cleanup] Images Deleted: {images_deleted}")
        print("=" * 60)
        
    except Exception as e:
        # Cleanup must never crash application startup
        print(f"[Cleanup Error] Execution failed: {e}")
        db.rollback()
        
    return records_deleted, images_deleted
