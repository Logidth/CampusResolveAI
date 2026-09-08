import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

import logging

logger = logging.getLogger("CampusResolveDB")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SQLITE_PATH = os.path.join(BASE_DIR, "campus_resolve.db")

raw_db_url = (os.getenv("DATABASE_URL") or "").strip()
if (raw_db_url.startswith('"') and raw_db_url.endswith('"')) or (raw_db_url.startswith("'") and raw_db_url.endswith("'")):
    raw_db_url = raw_db_url[1:-1].strip()

if not raw_db_url or raw_db_url.lower() in ("none", "null", "undefined", "false") or "://" not in raw_db_url:
    DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"
else:
    DATABASE_URL = raw_db_url

# Normalize Heroku/Render legacy postgres:// to modern postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

if DATABASE_URL.startswith("sqlite"):
    logger.info(f"Database initialized with SQLite: {DATABASE_URL}")
else:
    # Log masked URI for verification without leaking credentials
    try:
        masked_url = DATABASE_URL
        if "@" in masked_url:
            creds, host_part = masked_url.split("@", 1)
            scheme_user = creds.rsplit(":", 1)[0]
            masked_url = f"{scheme_user}:****@{host_part}"
        logger.info(f"Database initialized with PostgreSQL: {masked_url}")
    except Exception:
        logger.info("Database initialized with PostgreSQL")

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
