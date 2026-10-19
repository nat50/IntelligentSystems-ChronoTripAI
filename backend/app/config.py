from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHRONOTRIP_", env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'chronotrip.db').as_posix()}"
    data_dir: Path = BACKEND_DIR / "data"
    osrm_url: str = ""  # e.g. http://localhost:5000 ; empty = straight-line estimate
    osrm_profile: str = "driving"
    admin_token: str = ""  # empty = admin endpoints open (local development)
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    solver_time_limit_s: float = 6.0

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"


@lru_cache
def get_settings() -> Settings:
    return Settings()
