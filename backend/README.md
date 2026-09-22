# GateVision ANPR Backend

This is the production-ready backend for the GateVision ANPR (Automatic Number Plate Recognition) system. It uses FastAPI, Ultralytics YOLOv8, and EasyOCR to process simultaneous video streams from Entry/Exit lanes, correlating driver faces with vehicle license plates.

## Architecture

This backend implements a decoupled, event-driven streaming pipeline:
1. **PLATE Cameras** run a lightweight vehicle tracker. Upon detecting a mature track, they trigger exactly one frame for plate detection and OCR.
2. **DRIVER Cameras** run a person/face tracker. Upon detecting a face, they capture a crop.
3. **Event Matcher** (`services/matcher.py`) runs on a background thread. It correlates Driver and Plate events coming from the *same Gate* and *same Lane* within a configurable time window (default 2 seconds).
4. **VehicleEvent Database**: Correlated events (or timed-out partial events) are written to a single unified `vehicle_events` table via SQLAlchemy.

This design eliminates the lag associated with monolithic multi-frame OCR buffering and enables highly scalable, non-blocking asynchronous processing.

## Prerequisites

- Python 3.9+ 
- A CUDA-enabled GPU is strongly recommended for real-time video processing (YOLOv8 & EasyOCR).

## Installation

1. Open a terminal and navigate to this `backend` directory.
2. (Optional but recommended) Create a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/Mac:
   source venv/bin/activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

*Note: If you have a GPU, ensure you install the CUDA-specific versions of `torch` and `torchvision` after running the requirements.*

## Running the Application

To start the FastAPI server locally:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On the very first startup, the system will automatically:
1. Create the local SQLite database (`gatevision.db`).
2. Generate all the necessary tables (`vehicle_events`, `users`, `cameras`, `gates`).
3. Seed the default superadmin user.

### Default Login Credentials
- **Login ID:** `superadmin`
- **Password:** `ChangeMe123!`

## Testing the Pipelines

You can test the system using your dashboard frontend or tools like Postman/cURL by sending a POST request to `/stream/start`.

**Example: Start Driver Stream**
```json
POST http://localhost:8000/stream/start
{
    "url": "rtsp://...", 
    "camera_id": "DRIVER_CAM",
    "gate_id": "GATE_1",
    "lane": "ENTRY",
    "direction": "IN",
    "role": "DRIVER"
}
```

**Example: Start Plate Stream**
```json
POST http://localhost:8000/stream/start
{
    "url": "rtsp://...", 
    "camera_id": "PLATE_CAM",
    "gate_id": "GATE_1",
    "lane": "ENTRY",
    "direction": "IN",
    "role": "PLATE"
}
```

Watch the console logs to see the Event Matcher synchronizing the streams in real-time!

## Migration to PostgreSQL (Future Step)

The backend is currently configured to use a local SQLite database (`gatevision.db`) for rapid iteration and testing. Because we use SQLAlchemy, migrating to PostgreSQL for production is trivial:
1. Install the driver: `pip install psycopg2`
2. Update the `SQLALCHEMY_DATABASE_URL` in `database.py` to point to your PostgreSQL instance (e.g., `postgresql://user:password@localhost/dbname`).
