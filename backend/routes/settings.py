from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import List, Optional
import json
import os

from auth import require_permissions, get_current_user
from services.audit import set_audit_data

router = APIRouter(prefix="/settings", tags=["Settings"])

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(base_dir, "settings.json")


class CameraConfig(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool
    mode: str  # 'detection' or 'monitoring'

class SettingsUpdate(BaseModel):
    darkMode: bool
    compactTable: bool
    cameras: Optional[List[CameraConfig]] = None


@router.get("/")
def get_settings(current_user=Depends(get_current_user)):
    data = {
        "darkMode": True,
        "compactTable": False,
        "selected_model": "YOLOv8s",
        "cameras": []
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved_data = json.load(f)
                data.update(saved_data)
        except Exception:
            pass
    
    # Ensure default cameras exist if empty
    if not data.get("cameras"):
        data["cameras"] = [
            {"id": f"CAM_{i}", "name": f"CAM {i}", "url": f"rtsp://dummy/cam{i}", "enabled": True if i <= 8 else False, "mode": "detection" if i <= 2 else "monitoring"}
            for i in range(1, 9)
        ]
    return data



@router.put("/")
def update_settings(
    request: Request,
    payload: SettingsUpdate,
    current_user = Depends(require_permissions("users:manage")),
):
    """
    Update system configurations. Log change to audit log.
    """
    data = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
            
    old_value = json.dumps(data) if data else None
    
    data["darkMode"] = payload.darkMode
    data["compactTable"] = payload.compactTable
    if payload.cameras is not None:
        data["cameras"] = [cam.dict() for cam in payload.cameras]
    
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

    set_audit_data(
        request=request,
        action="Settings Updated",
        entity_type="Settings",
        entity_id=None,
        old_value=old_value,
        new_value=json.dumps(payload.dict()),
    )
    return payload
