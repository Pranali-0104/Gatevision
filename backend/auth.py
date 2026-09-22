from datetime import datetime, timedelta
import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import SessionLocal
import models


JWT_SECRET = os.getenv("VEHISCAN_JWT_SECRET", "change-this-secret-before-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("VEHISCAN_TOKEN_EXPIRE_MINUTES", "480"))
TEMP_PASSWORD = os.getenv("VEHISCAN_TEMP_PASSWORD", "ChangeMe123!")

ROLE_SUPER_ADMIN = "Super Admin"
ROLE_ADMIN = "Admin"
ROLE_OPERATOR = "Operator"
ROLE_VIEWER = "Viewer"

PERMISSIONS = {
    "records:view": "View vehicle records",
    "records:export": "Export vehicle records",
    "records:delete": "Delete vehicle records",
    "detection:run": "Run ANPR detection",
    "stream:view": "View live stream results",
    "stream:control": "Start and stop camera streams",
    "categories:view": "View categories",
    "categories:manage": "Create and delete categories",
    "hotlist:view": "View hotlist records",
    "hotlist:manage": "Create and delete hotlist records",
    "users:view": "View users",
    "users:manage": "Create, update, and delete users",
    "sessions:view": "View user login sessions",
    "audit_logs:view": "View audit logs",
}

ROLE_PERMISSION_MAP = {
    ROLE_SUPER_ADMIN: list(PERMISSIONS),
    ROLE_ADMIN: list(PERMISSIONS),
    ROLE_OPERATOR: [
        "records:view",
        "records:export",
        "detection:run",
        "stream:view",
        "stream:control",
        "categories:view",
        "hotlist:view",
        "hotlist:manage",
        "sessions:view",
    ],
    ROLE_VIEWER: [
        "records:view",
        "stream:view",
        "categories:view",
        "hotlist:view",
    ],
}

bearer_scheme = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _bcrypt():
    try:
        import bcrypt
    except ImportError as exc:
        raise RuntimeError("bcrypt is required. Install dependencies with: pip install -r requirements.txt") from exc
    return bcrypt


def hash_password(password: str) -> str:
    bcrypt = _bcrypt()
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    bcrypt = _bcrypt()
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: models.User, session_token_id: str | None = None) -> str:
    expires_at = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "login_id": user.login_id,
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }
    if session_token_id:
        payload["sid"] = session_token_id
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_user_roles(db: Session, user_id: int) -> list[str]:
    return [
        role.name
        for role in db.query(models.Role)
        .join(models.UserRole, models.UserRole.role_id == models.Role.id)
        .filter(models.UserRole.user_id == user_id)
        .order_by(models.Role.name)
        .all()
    ]


def get_user_permissions(db: Session, user_id: int) -> list[str]:
    return sorted({
        permission.code
        for permission in db.query(models.Permission)
        .join(models.RolePermission, models.RolePermission.permission_id == models.Permission.id)
        .join(models.UserRole, models.UserRole.role_id == models.RolePermission.role_id)
        .filter(models.UserRole.user_id == user_id)
        .all()
    })


def serialize_user(db: Session, user: models.User) -> dict:
    return {
        "id": user.id,
        "login_id": user.login_id,
        "employee_id": user.employee_id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "category": user.category,
        "lms_login": user.lms_login,
        "cms_login": user.cms_login,
        "is_active": bool(user.is_active),
        "roles": get_user_roles(db, user.id),
        "permissions": get_user_permissions(db, user.id),
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")
    return user


def require_permissions(*required_permissions: str):
    def dependency(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        user_permissions = set(get_user_permissions(db, current_user.id))
        if not set(required_permissions).issubset(user_permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency


def ensure_rbac_seed(db: Session):
    permissions = {}
    for code, description in PERMISSIONS.items():
        permission = db.query(models.Permission).filter(models.Permission.code == code).first()
        if not permission:
            permission = models.Permission(code=code, description=description)
            db.add(permission)
            db.flush()
        permissions[code] = permission

    roles = {}
    for role_name in ROLE_PERMISSION_MAP:
        role = db.query(models.Role).filter(models.Role.name == role_name).first()
        if not role:
            role = models.Role(name=role_name, description=f"{role_name} role")
            db.add(role)
            db.flush()
        roles[role_name] = role

    for role_name, permission_codes in ROLE_PERMISSION_MAP.items():
        role = roles[role_name]
        for code in permission_codes:
            exists = db.query(models.RolePermission).filter(
                models.RolePermission.role_id == role.id,
                models.RolePermission.permission_id == permissions[code].id,
            ).first()
            if not exists:
                db.add(models.RolePermission(role_id=role.id, permission_id=permissions[code].id))

    db.commit()
    return roles


def assign_roles(db: Session, user: models.User, role_names: list[str] | None):
    if role_names is None:
        return

    db.query(models.UserRole).filter(models.UserRole.user_id == user.id).delete()
    for role_name in role_names:
        role = db.query(models.Role).filter(models.Role.name == role_name).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role_name}")
        db.add(models.UserRole(user_id=user.id, role_id=role.id))
    db.commit()
