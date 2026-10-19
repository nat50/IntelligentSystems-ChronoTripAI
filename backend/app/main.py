from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from . import orm
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import admin, itinerary, places
from .services.versions import seed_country_stats, sync_from_disk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as s:
        seed_country_stats(s)
        sync_from_disk(s)
        # jobs interrupted by a restart can never finish
        s.execute(
            update(orm.TrainingJob)
            .where(orm.TrainingJob.status.in_(["queued", "running"]))
            .values(status="failed", message="Interrupted by a server restart")
        )
        s.commit()
    yield


app = FastAPI(title="ChronoTrip AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(places.router)
app.include_router(itinerary.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"ok": True}
