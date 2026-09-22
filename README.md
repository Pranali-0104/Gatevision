# 🚗 GateVision – Intelligent Automatic Number Plate Recognition (ANPR) System

GateVision is a production-grade, AI-powered Automatic Number Plate Recognition (ANPR) and vehicle monitoring system. It leverages a modern FastAPI backend combined with YOLO-based object detection and EasyOCR text recognition to achieve high-accuracy license plate extraction and live-stream monitoring.

---

## 🚀 Key Features

* 🧠 **YOLO-Based Plate Proposal:** High-precision localization of vehicle license plates using customized YOLO models.
* 🔍 **OCR Engine:** EasyOCR integration with localized plate format post-processing.
* 🎥 **Stream Resilience:** Heavy-duty RTSP/Webcam stream ingestion thread featuring:
  * Automatic disconnection drop-detection and socket recovery.
  * Progressive exponential backoff reconnection timers (5s, 5s, 10s, 30s max).
  * Lock-free CPU/GPU inference execution preventing API request blocking.
  * Secure credential masking and outage duration logging.
* 🚨 **Hotlist System:** Dynamic watchlist categories (e.g. VIP, Stolen, Suspicious) with visual highlights, custom emojis, and sound alarms.
* 📊 **Reporting & Audit Logs:** Detailed CSV and PDF exportable reports, coupled with database-backed security audit logs.
* ⚙️ **Production Model Selection:** Run-time model switching (YOLOv8n, YOLOv8s, YOLOv8m) with strict startup preloading checks.

---

## 🛠️ Tech Stack

* **Backend:** FastAPI, Uvicorn, SQLAlchemy
* **Database:** SQLite (ORM-managed)
* **AI/ML & CV:** OpenCV, YOLO (Ultralytics PyTorch), EasyOCR
* **Frontend:** Vanilla HTML5, CSS3 (sleek dark glassmorphic design), modern JavaScript (ES6)

---

## 📂 Project Structure

```text
fastapi/
│
├── backend/                  # FastAPI Application Root
│   ├── routes/               # API Router Handlers (Auth, Stream, Records, Dashboard, etc.)
│   ├── services/             # ANPR Ingestion, Stream Recovery, Cleanup, and Reports
│   ├── main.py               # Application Entry Point & Preloading logic
│   ├── database.py           # DB Connection Setup
│   ├── models.py             # DB Schema Definitions
│   ├── schemas.py            # Pydantic Schemas
│   ├── settings.json         # Active model configurations
│   └── *.pt                  # Model weights (Excluded from git; see Model Placement)
│
├── frontend/                 # Frontend Web Client
│   ├── css/                  # Custom CSS Stylesheets
│   ├── js/                   # Core application logic
│   └── index.html            # main SPA UI
│
├── docs/                     # System & API Documentation
└── requirements.txt          # Python Package Dependencies
```

---

## 🛠️ Local Setup Instructions

### 1. Prerequisites
* Python 3.8+
* C++ Build Tools (required for some OCR/OpenCV packages on Windows)

### 2. Set Up Virtual Environment
```bash
# Clone the repository
git clone <repository_url>
cd fastapi

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Model Weights Placement
Due to file sizes, YOLO weights are excluded from version control. Download and place the target weights in the `backend/` directory:
* `backend/yolov8n_plate.pt` (6.2 MB)
* `backend/yolov8s_plate.pt` (18.4 MB)
* `backend/yolov8m_plate.pt` (52.0 MB)

*Note: The server will refuse to start and raise a `FileNotFoundError` if the active model weights specified in `backend/settings.json` are missing.*

### 5. Running the Application
#### Run Backend Server:
```bash
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
The interactive Swagger API documentation is available at `http://127.0.0.1:8000/docs`.

#### Run Frontend:
Simply open `frontend/index.html` in your web browser or serve it statically.

---

## 🐧 Linux Production Deployment Instructions

For reliable production deployment on Linux (Ubuntu 20.04/22.04 LTS), it is recommended to run the FastAPI backend behind an **Nginx** reverse proxy and manage the uvicorn process via **Systemd**.

### 1. Systemd Service Configuration
Create a service file at `/etc/systemd/system/gatevision.service`:

```ini
[Unit]
Description=GateVision ANPR Service
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/gatevision/backend
Environment="PATH=/var/www/gatevision/.venv/bin"
ExecStart=/var/www/gatevision/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gatevision
sudo systemctl start gatevision
sudo systemctl status gatevision
```

### 2. Nginx Reverse Proxy Setup
Create an Nginx configuration file `/etc/nginx/sites-available/gatevision`:

```nginx
server {
    listen 80;
    server_name gatevision.local; # Or public IP / Domain

    # Frontend Static Files
    location / {
        root /var/www/gatevision/frontend;
        index index.html;
        try_files $uri $uri/ =404;
    }

    # Backend API requests
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Statically serve processed images
    location /storage/ {
        alias /var/www/gatevision/backend/storage/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/gatevision /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```
