from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
import os

from database import Base, SessionLocal, engine
from auth import ensure_rbac_seed, get_current_user
from routes import auth as auth_routes, detection, records, users, categories, hotlist, stream, sessions, audit_logs, settings, models as models_routes, dashboard as dashboard_routes
import jwt
from auth import JWT_SECRET, JWT_ALGORITHM
import models

app = FastAPI(title="GateVision API")

# Serve storage files statically
backend_dir = os.path.dirname(os.path.abspath(__file__))
storage_dir = os.path.join(backend_dir, "storage")
os.makedirs(storage_dir, exist_ok=True)
app.mount("/storage", StaticFiles(directory=storage_dir), name="storage")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    from fastapi import Request
    
    # Initialize request state variables to avoid AttributeError
    request.state.audit_action = None
    request.state.audit_entity_type = None
    request.state.audit_entity_id = None
    request.state.audit_old_value = None
    request.state.audit_new_value = None
    request.state.audit_user_id = None

    response = await call_next(request)

    # If an audited action was set and the response was successful, save the log
    action = request.state.audit_action
    if action and response.status_code < 400:
        # Extract user_id
        user_id = request.state.audit_user_id
        if user_id is None:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                try:
                    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                    user_id = int(payload.get("sub"))
                except Exception:
                    pass

        # Extract client IP
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else None

        with SessionLocal() as db:
            db_log = models.AuditLog(
                user_id=user_id,
                action=action,
                entity_type=request.state.audit_entity_type,
                entity_id=request.state.audit_entity_id,
                old_value=request.state.audit_old_value,
                new_value=request.state.audit_new_value,
                ip_address=ip_address,
            )
            db.add(db_log)
            db.commit()

    return response

Base.metadata.create_all(bind=engine)

def ensure_schema_updates():
    inspector = inspect(engine)
    
    if "records" in inspector.get_table_names():
        record_existing = {column["name"] for column in inspector.get_columns("records")}
        record_required = {
            "raw_text": "VARCHAR",
            "confidence": "INTEGER DEFAULT 0",
            "plate_image_url": "VARCHAR",
            "camera": "VARCHAR",
            "category_name": "VARCHAR",
            "category_code": "VARCHAR",
            "category_color": "VARCHAR",
            "model_used": "VARCHAR",
            "detector_used": "VARCHAR",
            "driver_image_url": "VARCHAR",
            "image_storage_type": "VARCHAR",
        }
        with engine.begin() as conn:
            for column, column_type in record_required.items():
                if column not in record_existing:
                    conn.execute(text(f"ALTER TABLE records ADD COLUMN {column} {column_type}"))

    if "categories" in inspector.get_table_names():
        category_existing = {column["name"] for column in inspector.get_columns("categories")}
        category_required = {
            "code": "VARCHAR",
            "color": "VARCHAR",
            "description": "VARCHAR",
            "has_sound_alert": "BOOLEAN DEFAULT 0",
            "has_visual_alert": "BOOLEAN DEFAULT 0",
        }
        with engine.begin() as conn:
            for column, column_type in category_required.items():
                if column not in category_existing:
                    conn.execute(text(f"ALTER TABLE categories ADD COLUMN {column} {column_type}"))

    if "users" in inspector.get_table_names():
        user_existing = {column["name"] for column in inspector.get_columns("users")}
        user_required = {
            "password_hash": "VARCHAR",
            "is_active": "BOOLEAN DEFAULT 1",
        }
        with engine.begin() as conn:
            for column, column_type in user_required.items():
                if column not in user_existing:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {column} {column_type}"))

    # Drop old watchlist table if it exists
    if "watchlist" in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE watchlist"))

ensure_schema_updates()
with SessionLocal() as db:
    ensure_rbac_seed(db)
    
    # Ensure default superadmin exists
    users_count = db.query(models.User).count()
    if users_count == 0:
        from auth import hash_password, TEMP_PASSWORD, ROLE_SUPER_ADMIN, assign_roles
        user = models.User(
            login_id="superadmin",
            employee_id="ADMIN-001",
            first_name="Super",
            last_name="Admin",
            category="A",
            lms_login="Y",
            cms_login="Y",
            password_hash=hash_password(TEMP_PASSWORD),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assign_roles(db, user, [ROLE_SUPER_ADMIN])
        print(f"[Startup] Created default Super Admin: login_id=superadmin password={TEMP_PASSWORD}")

    try:
        from services.reports import run_report_generation
        run_report_generation(db)
    except Exception as report_err:
        print(f"[Startup Warning] Startup report generation failed: {report_err}")
    try:
        from services.cleanup import run_cleanup
        run_cleanup(db)
    except Exception as cleanup_err:
        print(f"[Startup Warning] Startup cleanup job failed: {cleanup_err}")

app.include_router(detection.router)
app.include_router(records.router, prefix="/records")
app.include_router(users.router)
app.include_router(categories.router)
app.include_router(hotlist.router)
app.include_router(stream.router)
app.include_router(auth_routes.router)
app.include_router(sessions.router)
app.include_router(audit_logs.router)
app.include_router(settings.router)
app.include_router(models_routes.router)
app.include_router(dashboard_routes.router)


@app.on_event("startup")
def preload_models():
    import os
    from routes.models import load_selected_model
    from services.detection import get_detector
    
    active_model = load_selected_model()
    print(f"[ANPR] Active model configured: {active_model}")
    
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    active_weights = os.path.join(backend_dir, f"{active_model.lower()}_plate.pt")
    
    if not os.path.exists(active_weights):
        critical_error = f"CRITICAL: Active model weights file not found at {active_weights}. Startup aborted."
        print(critical_error)
        raise FileNotFoundError(critical_error)
        
    print(f"[ANPR] Preloading active model {active_model}...")
    try:
        get_detector(active_model)
        print(f"[ANPR] Active model {active_model} preloaded successfully.")
    except Exception as e:
        critical_error = f"CRITICAL: Failed to load active model {active_model}: {e}. Startup aborted."
        print(critical_error)
        raise RuntimeError(critical_error) from e

    # Also preload other available models to avoid runtime latency if selected later
    for model_name in ["YOLOv8n", "YOLOv8s", "YOLOv8m"]:
        if model_name == active_model:
            continue
        weights_file = os.path.join(backend_dir, f"{model_name.lower()}_plate.pt")
        if os.path.exists(weights_file):
            try:
                print(f"[ANPR] Preloading optional model {model_name}...")
                get_detector(model_name)
            except Exception as e:
                print(f"[ANPR Warning] Failed to preload optional {model_name}: {e}")


@app.get("/")
def root(current_user = Depends(get_current_user)):
    return {"message": "GateVision API running"}
