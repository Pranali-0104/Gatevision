from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import Base, SessionLocal, engine
from auth import ensure_rbac_seed

def main():
    print("Creating new tables sessions and audit_logs...")
    Base.metadata.create_all(bind=engine)
    
    print("Seeding permissions and mapping to roles...")
    with SessionLocal() as db:
        roles = ensure_rbac_seed(db)
        print(f"Seeding completed. Active roles seeded: {list(roles.keys())}")
        
    print("Sessions and Audit Log migration completed successfully.")

if __name__ == "__main__":
    main()
