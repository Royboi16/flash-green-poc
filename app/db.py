"""Database engine and session management using SQLAlchemy."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

Base = declarative_base()


def _build_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings.database_url
    engine_kwargs = {
        "pool_pre_ping": True,
        "future": True,
    }

    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool

    return create_engine(url, **engine_kwargs)


engine: Engine = _build_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def override_engine(database_url: str) -> Engine:
    """Reconfigure the global engine/session factory (useful for tests)."""

    global engine, SessionLocal

    engine = _build_engine(database_url)
    SessionLocal.configure(bind=engine)
    return engine


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session with commit/rollback semantics."""

    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive guard
        session.rollback()
        raise
    finally:
        session.close()

