"""Background dataset download started from the admin screen."""

from __future__ import annotations

import logging
import threading

from ml.download import download

from ..config import get_settings
from .training import dataset_found

log = logging.getLogger(__name__)
_lock = threading.Lock()
_state: dict = {"running": False, "progress": None, "error": None}


def status() -> dict:
    with _lock:
        return {"found": dataset_found(), "raw_dir": str(get_settings().raw_dir), **_state}


def start() -> dict:
    with _lock:
        if _state["running"]:
            raise RuntimeError("The dataset is already downloading")
        _state.update(running=True, progress=None, error=None)
    threading.Thread(target=_run, daemon=True, name="dataset-download").start()
    return status()


def _progress(p: dict) -> None:
    with _lock:
        _state["progress"] = {k: p.get(k) for k in ("stage", "file", "done", "total", "speed", "eta")}


def _run() -> None:
    try:
        download(get_settings().raw_dir, _progress)
    except Exception as exc:  # shown on the admin screen
        log.exception("dataset download failed")
        with _lock:
            _state["error"] = str(exc)[:500]
    finally:
        with _lock:
            _state["running"] = False
