# Production Readiness Review - Vehiscan ANPR

This document details the code audit, button validations, schema checks, and final deployment status of the Vehiscan ANPR system.

---

## 1. Subsystem Readiness Status

| Module | Status | Details |
| :--- | :--- | :--- |
| **Detection Storage & Crops** | `READY` | - Stores resized plate crops (max 300x100px) on disk in directory tree `storage/YYYY/MM/DD/plate_<id>.jpg` dynamically partitioned by detection timestamp.<br>- Returns base64 in responses for Phase A compatibility (with deprecation warning).<br>- Falls back to `None` on empty detections. |
| **Retention Cleanup** | `READY` | - Startup and cron task executes automatic 15-day cleanup policy.<br>- Purges SQLite database records and corresponding image crops from the filesystem.<br>- Standardized stdout logs logged cleanly. |
| **Dashboard Analytics** | `READY` | - Dedicated APIRouter `/dashboard/summary` mounted in uvicorn main app.<br>- Fully modular UI metrics grid (Today, VIP, Blacklist, Total Records) on the Live page.<br>- Updates on page load, manual upload detection, stream detection, and record deletion. |
| **PDF Reports** | `READY` | - Export formatted to fit A4 width (190mm).<br>- Dynamic file naming based on date filters (e.g. `2026-06-11_Report.pdf`, `JUNE2026.pdf`).<br>- Custom filter headers printed in PDF header.<br>- `"Records Returned: <count>"` printed instead of `"Total Records"`. |
| **User & Authentication** | `READY` | - Secure RBAC, JWT login session handling.<br>- Audit logs capture export parameters, manual detections, logins, logouts, and deletions. |

---

## 2. Audited Code Details

### Schema Checks
- Checked SQLite model `Record` in [models.py](file:///c:/Users/Pranali/Downloads/RTA/dashboard%20detection/fastapi/backend/models.py).
- Confirmed column `driver_image_url` is added and present. It is serializable and defaults to `None`.
- Column `image_storage_type` is present to differentiate filesystem storage from older database structures.

### UI Button & Input Validation
- Confirmed that the **CSV Export** button has been removed from the records page filters container.
- Verified that requesting a CSV export via direct URL (e.g. `/records/export?format=csv`) returns an HTTP 400 with a clean user-facing error details dictionary (`"detail": "CSV export is no longer supported. Use PDF."`).
- Verified that uvicorn CORS allows the frontend to execute fetches successfully.
- Added a `<select id="filterCamera">` filter to Records page, allowing filtering by camera `ENTRY_1`, `ENTRY_2`, `DRIVER_1`, matching the `/search` and `/export` API updates.

### Startup Integrity
- Verified uvicorn startup cleanup logic in `main.py`. The cleanup service handles empty database, missing folders, or connection issues gracefully without crashing uvicorn main startup process.
