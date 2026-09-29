"""Settings from the environment. `make` loads them from .env; inside Docker, Compose sets them."""

from __future__ import annotations

import os
from dataclasses import dataclass

from psycopg.conninfo import make_conninfo


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str
    group: str
    batch_size: int
    batch_wait_s: float
    lag_interval_s: float
    health_port: int
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str

    @property
    def conninfo(self) -> str:
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password,
            dbname=self.postgres_db,
        )

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            # On the host Redpanda listens on 19092; inside Compose on redpanda:9092.
            kafka_bootstrap=env.get("KAFKA_BOOTSTRAP", "localhost:19092"),
            group=env.get("CONSUMER_GROUP", "llobregat-consumer"),
            batch_size=int(env.get("CONSUMER_BATCH_SIZE", "500")),
            batch_wait_s=float(env.get("CONSUMER_BATCH_WAIT_S", "1")),
            lag_interval_s=float(env.get("CONSUMER_LAG_INTERVAL_S", "10")),
            health_port=int(env.get("CONSUMER_HEALTH_PORT", "8000")),
            postgres_host=env.get("POSTGRES_HOST", "localhost"),
            # On the host the database listens on POSTGRES_HOST_PORT; inside Compose on 5432.
            postgres_port=int(env.get("POSTGRES_PORT", env.get("POSTGRES_HOST_PORT", "15432"))),
            postgres_user=env.get("POSTGRES_USER", "llobregat"),
            postgres_password=env.get("POSTGRES_PASSWORD", ""),
            postgres_db=env.get("POSTGRES_DB", "logistics"),
        )
