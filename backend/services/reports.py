import os
import time
import base64
import calendar
from datetime import datetime, timedelta
from sqlalchemy import extract
from sqlalchemy.orm import Session
import cv2
import tempfile
from fpdf import FPDF

import models
from database import SessionLocal

# Column configuration matching printable A4 width of 190mm
PDF_COLUMNS = [
    {"header": "S.No", "width": 12, "type": "sno"},
    {"header": "License Image", "width": 35, "type": "image", "key": "plate_image_url"},
    {"header": "L.P. Number", "width": 35, "type": "text", "key": "plate"},
    {"header": "Time", "width": 38, "type": "datetime", "key": "time"},
    {"header": "Site Name", "width": 32, "type": "text", "key": "site"},
    {"header": "Camera Name", "width": 23, "type": "text", "key": "camera"},
    {"header": "Category", "width": 15, "type": "category", "key": "category"}
]

def generate_pdf_report(records, title: str, date_line: str, dest_path: str):
    """
    Generates a PDF report containing the list of records with embedded license plate images
    and saves it to the specified destination path.
    """
    pdf = FPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, title, 0, 1, 'C')
    pdf.ln(2)
    
    # Date Range Subtitle
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, date_line, 0, 1, 'C')
    pdf.ln(5)

    # Draw Table Headers
    pdf.set_fill_color(225, 225, 225)
    pdf.set_font('Arial', 'B', 9)
    for col in PDF_COLUMNS:
        pdf.cell(col["width"], 10, col["header"], 1, 0, 'C', fill=True)
    pdf.ln()
    
    # Draw Table Rows
    pdf.set_font('Arial', '', 9)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    for idx, r in enumerate(records):
        row_height = 20
        y_row = pdf.get_y()
        
        # Auto page break handling (Max Y is 270mm)
        if y_row + row_height > 270:
            pdf.add_page()
            # Redraw headers on new page
            pdf.set_fill_color(225, 225, 225)
            pdf.set_font('Arial', 'B', 9)
            for col in PDF_COLUMNS:
                pdf.cell(col["width"], 10, col["header"], 1, 0, 'C', fill=True)
            pdf.ln()
            pdf.set_font('Arial', '', 9)

        # Alternate row backgrounds (Zebra striping)
        is_striped = (idx % 2 == 1)
        if is_striped:
            pdf.set_fill_color(242, 242, 242)
        else:
            pdf.set_fill_color(255, 255, 255)

        for col in PDF_COLUMNS:
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
                            print(f"[Reports Export Warning] Failed to parse base64 image: {e}")
                    else:
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
                            
                            # Constraints: max width 31mm, max height 16mm
                            max_w_mm = w - 4.0
                            max_h_mm = row_height - 4.0
                            
                            w_mm = max_w_mm
                            h_mm = max_w_mm / aspect
                            if h_mm > max_h_mm:
                                h_mm = max_h_mm
                                w_mm = max_h_mm * aspect
                    except Exception as img_err:
                        print(f"[Reports Export Warning] Failed to inspect image size: {img_err}")
                        img_path = None
                        
                pdf.cell(w, row_height, "", 1, 0, 'C', fill=True)
                if img_path and w_mm > 0 and h_mm > 0:
                    try:
                        pad_x = (w - w_mm) / 2
                        pad_y = (row_height - h_mm) / 2
                        pdf.image(img_path, x + pad_x, y + pad_y, w_mm, h_mm)
                    except Exception as draw_err:
                        print(f"[Reports Export Warning] Failed to draw image in PDF: {draw_err}")
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
        
    # Ensure parent directory exists before saving
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    pdf.output(dest_path, 'F')
    print(f"[Reports] Report saved successfully to {dest_path}")

def run_report_generation(db: Session):
    """
    Main runner to automatically compile and archive missing daily and monthly reports.
    """
    print("=" * 60)
    print("[Reports] Running automatic report generation/archiving...")
    print("=" * 60)
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(base_dir, "storage", "reports")
    
    # 1. Daily Reports: Catch up on any missing daily reports in the last 15 days
    today = datetime.utcnow()
    for i in range(1, 16):  # Check the last 15 days (excluding today which is still in progress)
        dt = today - timedelta(days=i)
        
        month_str = dt.strftime("%B").upper() + str(dt.year)  # e.g., "MAY2026"
        day_filename = f"{month_str}_{dt.day}.pdf"
        dest_path = os.path.join(reports_dir, month_str, day_filename)
        
        if not os.path.exists(dest_path):
            # Query all records for this specific day
            start_time = datetime(dt.year, dt.month, dt.day, 0, 0, 0)
            end_time = datetime(dt.year, dt.month, dt.day, 23, 59, 59)
            
            day_records = db.query(models.VehicleEvent).filter(
                models.VehicleEvent.timestamp >= start_time,
                models.VehicleEvent.timestamp <= end_time
            ).order_by(models.VehicleEvent.timestamp.asc()).all()
            
            if len(day_records) > 0:
                print(f"[Reports] Generating missing daily report: {day_filename}")
                title = "Daily Transaction Report"
                date_line = f"Date: {dt.strftime('%Y-%m-%d')}  |  Records Count: {len(day_records)}"
                try:
                    generate_pdf_report(day_records, title, date_line, dest_path)
                except Exception as ex:
                    print(f"[Reports Error] Failed to generate daily report {day_filename}: {ex}")
            else:
                # No records for this day, skip generating empty reports
                pass

    # 2. Monthly Reports: Find any fully completed months in the database that lack a monthly report
    try:
        # Get all distinct month/year combinations in the database
        db_months = db.query(
            extract('year', models.VehicleEvent.timestamp).label('year'),
            extract('month', models.VehicleEvent.timestamp).label('month')
        ).distinct().all()
        
        for yr, mn in db_months:
            if not yr or not mn:
                continue
            
            # Check if this month has ended (i.e. the current year/month is greater than yr/mn)
            if yr > today.year or (yr == today.year and mn >= today.month):
                # This month is still ongoing, do not generate the monthly report yet
                continue
                
            month_datetime = datetime(int(yr), int(mn), 1)
            month_str = month_datetime.strftime("%B").upper() + str(yr)  # e.g., "MAY2026"
            monthly_filename = f"{month_str}.pdf"
            dest_path = os.path.join(reports_dir, month_str, monthly_filename)
            
            if not os.path.exists(dest_path):
                # Determine date range for this month
                last_day = calendar.monthrange(int(yr), int(mn))[1]
                start_time = datetime(int(yr), int(mn), 1, 0, 0, 0)
                end_time = datetime(int(yr), int(mn), last_day, 23, 59, 59)
                
                month_records = db.query(models.VehicleEvent).filter(
                    models.VehicleEvent.timestamp >= start_time,
                    models.VehicleEvent.timestamp <= end_time
                ).order_by(models.VehicleEvent.timestamp.asc()).all()
                
                if len(month_records) > 0:
                    print(f"[Reports] Generating missing monthly report: {monthly_filename}")
                    title = f"Monthly Transaction Report - {month_datetime.strftime('%B %Y')}"
                    date_line = f"Month: {month_datetime.strftime('%B %Y')}  |  Records Count: {len(month_records)}"
                    try:
                        generate_pdf_report(month_records, title, date_line, dest_path)
                    except Exception as ex:
                        print(f"[Reports Error] Failed to generate monthly report {monthly_filename}: {ex}")
    except Exception as ex:
        print(f"[Reports Error] Failed during monthly report scanning: {ex}")
        
    print("=" * 60)
