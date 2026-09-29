"""Settings from the environment. `make` loads them from .env; inside Docker, Compose sets them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

GENERATOR_DIR = Path(__file__).resolve().parents[1]
BRONZE_BUCKET = "bronze"


@dataclass(frozen=True)
class Settings:
    seed_dir: Path
    cache_dir: Path
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            seed_dir=Path(env.get("GENERATOR_SEED_DIR", GENERATOR_DIR / "seed")),
            cache_dir=Path(env.get("GENERATOR_CACHE_DIR", GENERATOR_DIR / ".cache")),
            postgres_host=env.get("POSTGRES_HOST", "localhost"),
            # On the host the database listens on POSTGRES_HOST_PORT; inside Compose on 5432.
            postgres_port=int(env.get("POSTGRES_PORT", env.get("POSTGRES_HOST_PORT", "15432"))),
            postgres_user=env.get("POSTGRES_USER", "llobregat"),
            postgres_password=env.get("POSTGRES_PASSWORD", ""),
            postgres_db=env.get("POSTGRES_DB", "logistics"),
            s3_endpoint=env.get("S3_ENDPOINT", "http://localhost:9000"),
            s3_access_key=env.get("S3_ACCESS_KEY", ""),
            s3_secret_key=env.get("S3_SECRET_KEY", ""),
        )
