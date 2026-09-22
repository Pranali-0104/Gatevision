from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from database import Base
from datetime import datetime

class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Gate(Base):
    __tablename__ = "gates"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    site_id = Column(Integer)


class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    site_id = Column(Integer)
    gate_id = Column(Integer, nullable=True)
    role = Column(String, default="PLATE") # DRIVER or PLATE
    lane = Column(String, default="ENTRY") # ENTRY or EXIT
    direction = Column(String, nullable=True)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    code = Column(String, unique=True)
    icon = Column(String)
    color = Column(String)
    description = Column(String)
    has_sound_alert = Column(Boolean, default=False)
    has_visual_alert = Column(Boolean, default=False)


class VehicleEvent(Base):
    __tablename__ = "vehicle_events"

    id = Column(Integer, primary_key=True, index=True)
    
    gate_id = Column(String, nullable=True)
    lane = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    plate_text = Column(String, nullable=True)
    plate_image_url = Column(String, nullable=True)
    vehicle_image_url = Column(String, nullable=True)
    driver_image_url = Column(String, nullable=True)
    
    confidence = Column(Integer, default=0)
    
    camera_plate = Column(String, nullable=True)
    camera_driver = Column(String, nullable=True)
    
    # Keeping category details for compatibility with hotlist logic
    category = Column(String, nullable=True)
    category_name = Column(String, nullable=True)
    category_code = Column(String, nullable=True)
    category_color = Column(String, nullable=True)
    
    model_used = Column(String, nullable=True)
    detector_used = Column(String, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    login_id = Column(String, unique=True, index=True)
    employee_id = Column(String)

    first_name = Column(String)
    last_name = Column(String)

    category = Column(String)  # A / B / etc

    lms_login = Column(String)  # Y / N
    cms_login = Column(String)  # Y / N
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)

    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

class Hotlist(Base):
    __tablename__ = "hotlist"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String, unique=True, index=True)
    category_id = Column(Integer)  # Treating as FK logically, simple int in SQLite
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, default="System")


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    login_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    logout_time = Column(DateTime, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    access_status = Column(String, nullable=False)
    session_token_id = Column(String, unique=True, index=True, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
