from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
import json
import base64
import cv2
from services.audit import set_audit_data
from sqlalchemy.orm import Session
from datetime import datetime, time
import io
import csv
import tempfile
import os
from fpdf import FPDF

from database import SessionLocal
from auth import require_permissions
import models  # make sure this exists

router = APIRouter()

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/search")
def search_records(
    plate: Optional[str] = "",
    category: Optional[str] = "",
    gate_id: Optional[str] = "",
    lane: Optional[str] = "",
    from_date: Optional[str] = "",
    to_date: Optional[str] = "",
    from_time: Optional[str] = "",
    to_time: Optional[str] = "",
    include_repeated: Optional[bool] = False,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("records:view"))
):
    query = db.query(models.VehicleEvent)

    if plate:
        query = query.filter(models.VehicleEvent.plate_text.contains(plate))

    if category:
        query = query.filter(models.VehicleEvent.category == category)

    if gate_id:
        query = query.filter(models.VehicleEvent.gate_id == gate_id)

    if lane:
        query = query.filter(models.VehicleEvent.lane == lane)

    if from_date:
        start_date = datetime.strptime(from_date, "%Y-%m-%d")
        if from_time:
            time_obj = datetime.strptime(from_time, "%H:%M").timestamp()
            start_date = datetime.combine(start_date.date(), time_obj)
        query = query.filter(models.VehicleEvent.timestamp >= start_date)

    if to_date:
        end_date = datetime.strptime(to_date, "%Y-%m-%d")
        if to_time:
            time_obj = datetime.strptime(to_time, "%H:%M").timestamp()
            end_date = datetime.combine(end_date.date(), time_obj)
        else:
            end_date = datetime.combine(end_date.date(), time.max)
        query = query.filter(models.VehicleEvent.timestamp <= end_date)

    results = query.order_by(models.VehicleEvent.timestamp.desc()).limit(50).all()

    return [serialize_record(r) for r in results]

@router.get("/export")
def export_records(
    request: Request,
    plate: Optional[str] = "",
    category: Optional[str] = "",
    gate_id: Optional[str] = "",
    lane: Optional[str] = "",
    from_date: Optional[str] = "",
    to_date: Optional[str] = "",
    from_time: Optional[str] = "",
    to_time: Optional[str] = "",
    include_repeated: Optional[bool] = False,
    format: str = "pdf",
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("records:export"))
):
    if format != "pdf":
        raise HTTPException(
            status_code=400,
            detail="CSV export is no longer supported. Use PDF."
        )

    query = db.query(models.VehicleEvent)

    if plate:
        query = query.filter(models.VehicleEvent.plate_text.contains(plate))

    if category:
        query = query.filter(models.VehicleEvent.category == category)

    if gate_id:
        query = query.filter(models.VehicleEvent.gate_id == gate_id)

    if lane:
        query = query.filter(models.VehicleEvent.lane == lane)
    if from_date:
        start_date = datetime.strptime(from_date, "%Y-%m-%d")
        if from_time:
            time_obj = datetime.strptime(from_time, "%H:%M").timestamp()
            start_date = datetime.combine(start_date.date(), time_obj)
        query = query.filter(models.VehicleEvent.timestamp >= start_date)

    if to_date:
        end_date = datetime.strptime(to_date, "%Y-%m-%d")
        if to_time:
            time_obj = datetime.strptime(to_time, "%H:%M").timestamp()
            end_date = datetime.combine(end_date.date(), time_obj)
        else:
            end_date = datetime.combine(end_date.date(), time.max)
        query = query.filter(models.VehicleEvent.timestamp <= end_date)

    results = query.order_by(models.VehicleEvent.timestamp.desc()).all()

    # Log audit event
    filter_summary = f"Format: {format}, Filters: Plate={plate}, Category={category}, Site={site}, Camera={camera}, Range={from_date} to {to_date}"
    set_audit_data(
        request=request,
        action="Record Exported",
        entity_type="Record",
        entity_id=None,
        old_value=None,
        new_value=filter_summary,
    )

    filename = "records.pdf"
    if from_date and to_date:
        if from_date == to_date:
            filename = f"{from_date}_Report.pdf"
        else:
            try:
                start_dt = datetime.strptime(from_date, "%Y-%m-%d")
                end_dt = datetime.strptime(to_date, "%Y-%m-%d")
                import calendar
                last_day = calendar.monthrange(start_dt.year, start_dt.month)[1]
                if start_dt.month == end_dt.month and start_dt.year == end_dt.year and start_dt.day == 1 and end_dt.day == last_day:
                    month_name = start_dt.strftime("%B").upper()
                    filename = f"{month_name}{start_dt.year}.pdf"
                else:
                    filename = f"{from_date}_to_{to_date}_Report.pdf"
            except Exception:
                filename = f"{from_date}_to_{to_date}_Report.pdf"
    elif from_date:
        filename = f"{from_date}_Report.pdf"

    pdf = FPDF()
    pdf.add_page()
    
    # Header block matching the screenshot
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Transaction Report', 0, 1, 'C')
    pdf.ln(2)
    
    pdf.set_font('Arial', '', 9)
    start_date_str = f"{from_date} 00:00:00" if from_date else "-"
    end_date_str = f"{to_date} 23:59:59" if to_date else "-"
    date_line = f"Start Date :  {start_date_str}      End Date :  {end_date_str}"
    pdf.cell(0, 5, date_line, 0, 1, 'C')
    pdf.ln(5)

    # Column configuration matching printable A4 width of 190mm and the screenshot exactly
    pdf_columns = [
        {"header": "S.No", "width": 12, "type": "sno"},
        {"header": "License Image", "width": 35, "type": "image", "key": "plate_image_url"},
        {"header": "L.P. Number", "width": 35, "type": "text", "key": "plate"},
        {"header": "Time", "width": 38, "type": "datetime", "key": "time"},
        {"header": "Site Name", "width": 32, "type": "text", "key": "site"},
        {"header": "Camera Name", "width": 23, "type": "text", "key": "camera"},
        {"header": "Category", "width": 15, "type": "category", "key": "category"}
    ]

    # Draw Table Headers with light gray background fill
    pdf.set_fill_color(225, 225, 225)
    pdf.set_font('Arial', 'B', 9)
    for col in pdf_columns:
        pdf.cell(col["width"], 10, col["header"], 1, 0, 'C', fill=True)
    pdf.ln()
    
    # Draw Table Rows
    pdf.set_font('Arial', '', 9)
    for idx, r in enumerate(results):
        row_height = 20
        
        # Start position of current row
        x_row = pdf.get_x()
        y_row = pdf.get_y()
        
        # Auto page break handling (Max Y is 270mm)
        if y_row + row_height > 270:
            pdf.add_page()
            x_row = pdf.get_x()
            y_row = pdf.get_y()
            # Redraw headers on new page
            pdf.set_fill_color(225, 225, 225)
            pdf.set_font('Arial', 'B', 9)
            for col in pdf_columns:
                pdf.cell(col["width"], 10, col["header"], 1, 0, 'C', fill=True)
            pdf.ln()
            pdf.set_font('Arial', '', 9)
            x_row = pdf.get_x()
            y_row = pdf.get_y()

        # Alternate row backgrounds (Zebra striping matching the screenshot)
        is_striped = (idx % 2 == 1)
        if is_striped:
            pdf.set_fill_color(242, 242, 242) # Light gray
        else:
            pdf.set_fill_color(255, 255, 255) # White

        for col in pdf_columns:
            x = pdf.get_x()
            y = pdf.get_y()
            w = col["width"]
            col_type = col["type"]
            
            if col_type == "sno":
                pdf.cell(w, row_height, str(idx + 1), 1, 0, 'C', fill=True)
            elif col_type == "image":
                col_key = col["key"]
                val = getattr(r, col_key, None)
                img_path = None
                img_is_temp = False
                w_mm, h_mm = 0.0, 0.0
                
                if val and val.strip():
                    if val.startswith("data:image"):
                        try:
                            header, encoded = val.split(",", 1)
                            img_data = base64.b64decode(encoded)
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as img_tmp:
                                img_tmp.write(img_data)
                                img_path = img_tmp.name
                            img_is_temp = True
                        except Exception as e:
                            print(f"[Export Warning] Failed to parse base64 image: {e}")
                    else:
                        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        full_path = os.path.join(base_dir, val.lstrip('/\\'))
                        if os.path.exists(full_path):
                            img_path = full_path
                        elif os.path.exists(val):
                            img_path = val
                        
                if img_path:
                    try:
                        img = cv2.imread(img_path)
                        if img is not None:
                            h_img, w_img = img.shape[:2]
                            aspect = w_img / h_img
                            
                            # Max constraints in mm: width 35mm
                            max_w_mm = w - 4.0
                            max_h_mm = row_height - 4.0
                            
                            w_mm = max_w_mm
                            h_mm = max_w_mm / aspect
                            if h_mm > max_h_mm:
                                h_mm = max_h_mm
                                w_mm = max_h_mm * aspect
                    except Exception as img_err:
                        print(f"[Export Warning] Failed to inspect image size: {img_err}")
                        img_path = None
                        
                pdf.cell(w, row_height, "", 1, 0, 'C', fill=True)
                if img_path and w_mm > 0 and h_mm > 0:
                    try:
                        pad_x = (w - w_mm) / 2
                        pad_y = (row_height - h_mm) / 2
                        pdf.image(img_path, x + pad_x, y + pad_y, w_mm, h_mm)
                    except Exception as draw_err:
                        print(f"[Export Warning] Failed to draw image in PDF: {draw_err}")
                        pdf.set_xy(x, y)
                        pdf.cell(w, row_height, "Error", 0, 0, 'C')
                else:
                    pdf.set_xy(x, y)
                    pdf.cell(w, row_height, "No Image", 0, 0, 'C')
                    
                if img_path and img_is_temp:
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass
                        
                pdf.set_xy(x + w, y)
                
            else:
                col_key = col["key"]
                if col_type == "datetime":
                    val_dt = getattr(r, col_key, None)
                    val_str = val_dt.strftime('%Y-%m-%d %H:%M:%S') if val_dt else '-'
                elif col_key == "category":
                    val_str = r.category_name or r.category or "Unknown"
                else:
                    val_raw = getattr(r, col_key, "-")
                    val_str = str(val_raw) if val_raw is not None else "-"
                
                pdf.cell(w, row_height, val_str, 1, 0, 'C', fill=True)
        pdf.ln(row_height)
        
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name, 'F')
        tmp_name = tmp.name
        
    with open(tmp_name, 'rb') as f:
        pdf_data = f.read()
    os.remove(tmp_name)
    
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def serialize_record(record: models.VehicleEvent) -> dict:
    return {
        "id": record.id,
        "gate_id": record.gate_id,
        "lane": record.lane,
        "direction": record.direction,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "plate_text": record.plate_text,
        "plate_image_url": record.plate_image_url,
        "vehicle_image_url": record.vehicle_image_url,
        "driver_image_url": record.driver_image_url,
        "confidence": record.confidence,
        "camera_plate": record.camera_plate,
        "camera_driver": record.camera_driver,
        "category": record.category,
        "category_name": record.category_name,
        "category_code": record.category_code,
        "category_color": record.category_color,
        "model_used": record.model_used,
        "detector_used": record.detector_used,
    }


@router.delete("/{record_id}")
def delete_record(
    request: Request,
    record_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("records:delete")),
):
    record = db.query(models.VehicleEvent).filter(models.VehicleEvent.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    # Delete filesystem crop image if it exists
    img_url = record.plate_image_url
    if img_url and not img_url.startswith("data:image"):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(base_dir, img_url.lstrip('/\\'))
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                print(f"[Warning] Failed to delete file {full_path}: {e}")

    record_dict = serialize_record(record)

    db.delete(record)
    db.commit()

    set_audit_data(
        request=request,
        action="Record Deleted",
        entity_type="Record",
        entity_id=record_id,
        old_value=json.dumps(record_dict),
        new_value=None,
    )

    return {"message": "Record deleted successfully", "record": record_dict}


@router.get("/archive")
def get_reports_archive(
    current_user = Depends(require_permissions("records:view"))
):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(base_dir, "storage", "reports")
    
    if not os.path.exists(reports_dir):
        return []
        
    archive_data = {}
    
    for folder_name in sorted(os.listdir(reports_dir), reverse=True):
        folder_path = os.path.join(reports_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
            
        daily_reports = []
        monthly_report = None
        
        for file_name in sorted(os.listdir(folder_path)):
            if not file_name.endswith(".pdf"):
                continue
                
            file_path = os.path.join(folder_path, file_name)
            size_kb = round(os.path.getsize(file_path) / 1024.0, 1)
            relative_url = f"storage/reports/{folder_name}/{file_name}"
            
            if file_name == f"{folder_name}.pdf":
                monthly_report = {
                    "filename": file_name,
                    "url": relative_url,
                    "size_kb": size_kb
                }
            else:
                parts = file_name.replace(".pdf", "").split("_")
                day_num = None
                if len(parts) > 1 and parts[1].isdigit():
                    day_num = int(parts[1])
                
                daily_reports.append({
                    "filename": file_name,
                    "url": relative_url,
                    "day": day_num,
                    "size_kb": size_kb
                })
        
        daily_reports.sort(key=lambda x: x["day"] if x["day"] is not None else 0)
        
        if monthly_report or daily_reports:
            archive_data[folder_name] = {
                "month_name": folder_name,
                "monthly_report": monthly_report,
                "daily_reports": daily_reports
            }
            
    def month_sort_key(name):
        for month_num in range(1, 13):
            m_name = datetime(2000, month_num, 1).strftime("%B").upper()
            if name.startswith(m_name):
                year_part = name.replace(m_name, "")
                if year_part.isdigit():
                    return int(year_part), month_num
        return 0, 0
        
    sorted_archive = [archive_data[k] for k in sorted(archive_data.keys(), key=month_sort_key, reverse=True)]
    return sorted_archive


@router.get("/archive/download")
def download_reports_archive(
    path: str,
    current_user = Depends(require_permissions("records:export"))
):
    from fastapi.responses import FileResponse
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base_dir, path)
    
    normalized_path = os.path.normpath(full_path)
    reports_dir = os.path.normpath(os.path.join(base_dir, "storage", "reports"))
    
    if not normalized_path.startswith(reports_dir):
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not os.path.exists(normalized_path) or not os.path.isfile(normalized_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    filename = os.path.basename(normalized_path)
    return FileResponse(
        normalized_path,
        media_type="application/pdf",
        filename=filename
    )

