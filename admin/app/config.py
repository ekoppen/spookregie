import os
from dataclasses import dataclass


@dataclass
class Settings:
    admin_password: str
    db_path: str
    media_dir: str
    port: int
    # Zelfde LOG_DIR-conventie als de nodes; default achteraan zodat bestaande
    # aanroepen zonder log_dir blijven werken.
    log_dir: str = "./logs"


def get_settings():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError(
            "ADMIN_PASSWORD moet ingesteld zijn (geen standaardwaarde om veiligheidsredenen)"
        )
    return Settings(
        admin_password=admin_password,
        db_path=os.environ.get("ADMIN_DB_PATH", "./admin.db"),
        media_dir=os.environ.get("ADMIN_MEDIA_DIR", "./media_store"),
        port=int(os.environ.get("ADMIN_PORT", "8000")),
        log_dir=os.environ.get("LOG_DIR", "./logs"),
    )
