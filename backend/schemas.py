from pydantic import BaseModel
from datetime import datetime


class VehicleEventCreate(BaseModel):
    gate_id: str | None = None
    lane: str | None = None
    direction: str | None = None
    plate_text: str | None = None
    plate_image_url: str | None = None
    vehicle_image_url: str | None = None
    driver_image_url: str | None = None
    confidence: int = 0
    camera_plate: str | None = None
    camera_driver: str | None = None
    category: str | None = None
    category_name: str | None = None
    category_code: str | None = None
    category_color: str | None = None
    model_used: str | None = None
    detector_used: str | None = None


class VehicleEventOut(BaseModel):
    id: int
    gate_id: str | None = None
    lane: str | None = None
    direction: str | None = None
    timestamp: datetime
    plate_text: str | None = None
    plate_image_url: str | None = None
    vehicle_image_url: str | None = None
    driver_image_url: str | None = None
    confidence: int
    camera_plate: str | None = None
    camera_driver: str | None = None
    category: str | None = None
    category_name: str | None = None
    category_code: str | None = None
    category_color: str | None = None
    model_used: str | None = None
    detector_used: str | None = None

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    login_id: str
    employee_id: str
    first_name: str
    last_name: str
    category: str
    lms_login: str
    cms_login: str
    password: str | None = None
    roles: list[str] | None = None


class UserUpdate(BaseModel):
    login_id: str
    employee_id: str
    first_name: str
    last_name: str
    category: str
    lms_login: str
    cms_login: str
    password: str | None = None
    roles: list[str] | None = None


class UserOut(BaseModel):
    id: int
    login_id: str
    employee_id: str
    first_name: str
    last_name: str
    category: str
    lms_login: str
    cms_login: str
    is_active: bool = True
    roles: list[str] = []
    permissions: list[str] = []

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    login_id: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class CategoryCreate(BaseModel):
    name: str
    code: str
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    has_sound_alert: bool = False
    has_visual_alert: bool = False

class CategoryOut(BaseModel):
    id: int
    name: str
    code: str
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    has_sound_alert: bool = False
    has_visual_alert: bool = False

    class Config:
        from_attributes = True

class HotlistCreate(BaseModel):
    plate_number: str
    category_id: int

class HotlistOut(BaseModel):
    id: int
    plate_number: str
    category_id: int
    created_at: datetime
    created_by: str
    
    # Nested fields for UI convenience
    category_name: str | None = None
    category_icon: str | None = None
    category_color: str | None = None
    has_sound_alert: bool = False
    has_visual_alert: bool = False

    class Config:
        from_attributes = True
