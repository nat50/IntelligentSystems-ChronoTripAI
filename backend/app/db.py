from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def init_db() -> None:
    from . import orm  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # PostGIS geography column + GiST index for spatial queries
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(
                text(
                    "ALTER TABLE places ADD COLUMN IF NOT EXISTS geom geography(Point, 4326) "
                    "GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED"
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_places_geom ON places USING GIST (geom)"))
