from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text

from auth import ROLE_SUPER_ADMIN, ROLE_VIEWER, TEMP_PASSWORD, assign_roles, ensure_rbac_seed, hash_password
from database import Base, SessionLocal, engine
import models


def add_user_auth_columns():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("users")}
    required = {
        "password_hash": "VARCHAR",
        "is_active": "BOOLEAN DEFAULT 1",
    }

    with engine.begin() as conn:
        for column, column_type in required.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {column} {column_type}"))


def migrate_users(db):
    users = db.query(models.User).order_by(models.User.id).all()
    if not users:
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
        print(f"Created bootstrap Super Admin: login_id=superadmin password={TEMP_PASSWORD}")
        return

    for index, user in enumerate(users):
        changed = False
        if not user.password_hash:
            user.password_hash = hash_password(TEMP_PASSWORD)
            changed = True
        if user.is_active is None:
            user.is_active = True
            changed = True
        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

        existing_roles = [
            role.name
            for role in db.query(models.Role)
            .join(models.UserRole, models.UserRole.role_id == models.Role.id)
            .filter(models.UserRole.user_id == user.id)
            .all()
        ]
        if not existing_roles:
            assign_roles(db, user, [ROLE_SUPER_ADMIN if index == 0 else ROLE_VIEWER])

    print(f"Migrated {len(users)} existing users. Temporary password: {TEMP_PASSWORD}")


def main():
    Base.metadata.create_all(bind=engine)
    add_user_auth_columns()
    with SessionLocal() as db:
        ensure_rbac_seed(db)
        migrate_users(db)
    print("Auth/RBAC migration completed.")


if __name__ == "__main__":
    main()
