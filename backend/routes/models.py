from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
import os
import json

from auth import require_permissions
from services.audit import set_audit_data

router = APIRouter(prefix="/models", tags=["Models"])

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(base_dir, "settings.json")
DEFAULT_MODEL = "YOLOv8n"
MODEL_OPTIONS = ["YOLOv8n", "YOLOv8s", "YOLOv8m", "YOLOv8l", "YOLOv8x"]

def load_selected_model():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                return data.get("selected_model", DEFAULT_MODEL)
        except Exception:
            pass
    return DEFAULT_MODEL

def save_selected_model(model_name: str):
    data = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    data["selected_model"] = model_name
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


class ModelSelect(BaseModel):
    model: str


@router.get("/")
def get_models(current_user = Depends(require_permissions("records:view"))):
    active_model = load_selected_model()
    return {
        "models": [
            {"name": "YOLOv8n", "available": os.path.exists(os.path.join(base_dir, "yolov8n_plate.pt")), "experimental": False},
            {"name": "YOLOv8s", "available": os.path.exists(os.path.join(base_dir, "yolov8s_plate.pt")), "experimental": False},
            {"name": "YOLOv8m", "available": os.path.exists(os.path.join(base_dir, "yolov8m_plate.pt")), "experimental": True},
            {"name": "YOLOv8l", "available": False, "experimental": False},
            {"name": "YOLOv8x", "available": False, "experimental": False}
        ],
        "active": active_model
    }

@router.post("/select")
def select_model(
    request: Request,
    payload: ModelSelect,
    current_user = Depends(require_permissions("users:manage"))
):
    selected = payload.model
    if selected not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid model option")
        
    weights_path = os.path.join(base_dir, f"{selected.lower()}_plate.pt")
    if not os.path.exists(weights_path):
        raise HTTPException(
            status_code=400,
            detail=f"Model weights file for {selected} is not present in deployment. Please load it to backend/{selected.lower()}_plate.pt first."
        )
        
    old_model = load_selected_model()
    save_selected_model(selected)
    
    # Log audit event
    set_audit_data(
        request=request,
        action="Detection Model Selected",
        entity_type="Model",
        entity_id=None,
        old_value=old_model,
        new_value=selected,
    )
    
    return {"message": "Model selected successfully", "active": selected}
