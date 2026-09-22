from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
import os
import uuid
import tempfile
from pathlib import Path
from auth import require_permissions
import services.stream as stream_service

router = APIRouter(prefix="/stream", tags=["Stream"])

class StreamStartRequest(BaseModel):
    url: str
    camera_id: str
    gate_id: str = "GATE_1"
    lane: str = "ENTRY"
    direction: str = "IN"
    role: str = "PLATE"
    mode: str = "detection"
    stream_type: str = "main"

@router.post("/start")
def start_stream(
    req: StreamStartRequest,
    current_user = Depends(require_permissions("stream:control")),
):
    if not stream_service.start_stream(req.url, req.camera_id, req.gate_id, req.lane, req.direction, req.role, req.mode, req.stream_type):
        raise HTTPException(status_code=400, detail="Stream already running")
    return {"message": f"Stream started for {req.camera_id}"}

@router.post("/upload")
async def upload_stream(
    file: UploadFile = File(...),
    current_user = Depends(require_permissions("stream:control")),
):
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(base_dir, "storage", "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
    with os.fdopen(fd, "wb") as f:
        contents = await file.read()
        f.write(contents)
        
    camera_id = f"CAM_UPLOAD_{uuid.uuid4().hex[:8].upper()}"
    
    if not stream_service.start_stream(temp_path, camera_id, "UPLOAD_GATE", "UPLOAD_LANE", "IN", "PLATE", "detection", "main", is_upload=True):
        raise HTTPException(status_code=400, detail="Failed to start virtual stream")
        
    return {"camera_id": camera_id, "status": "started"}

@router.post("/stop")
def stop_stream(camera_id: str = None, current_user = Depends(require_permissions("stream:control"))):
    stream_service.stop_stream(camera_id)
    return {"message": "Stream stopped"}

@router.get("/latest")
def get_latest(current_user = Depends(require_permissions("stream:view"))):
    result = stream_service.get_latest_result()
    if not result:
        return {"status": "waiting"}
    return result
