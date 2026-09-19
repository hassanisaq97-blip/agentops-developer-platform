"""Database-engine og session-håndtering.

Vi bruger synkron SQLAlchemy (psycopg3-driver mod PostgreSQL, i tests mod
SQLite). Det er en bevidst simplificering for dette projekts skala — se
docs/adr/0006-postgresql-persistence.md for afvejningen mod async SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from agentops.settings import Settings, get_settings

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Base(DeclarativeBase):
    pass


def run_migrations(settings: Settings) -> None:
    """Bringer databaseskemaet up to date via Alembic — brugt ved rigtig app-opstart.

    Adskilt fra `create_all_tables()`, som er en hurtig genvej brugt i tests:
    her ønsker vi et versioneret, reversibelt skema (se migrations/), ikke blot
    "opret det, hvis det mangler".
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def build_engine(settings: Settings) -> Engine:
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(settings: Settings | None = None) -> None:
    global _engine, _SessionLocal
    settings = settings or get_settings()
    _engine = build_engine(settings)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def create_all_tables() -> None:
    if _engine is None:
        init_engine()
    assert _engine is not None
    Base.metadata.create_all(bind=_engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
