"""Settings from the environment, on top of the generator's (database, bucket and seeds).

`make` loads them from .env; inside Docker, Compose sets them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from llobregat_generator.config import Settings


@dataclass(frozen=True)
class SimulatorSettings:
    base: Settings
    osrm_url: str
    kafka_bootstrap: str

    @classmethod
    def from_env(cls) -> SimulatorSettings:
        return cls(
            base=Settings.from_env(),
            osrm_url=os.environ.get("OSRM_URL", "http://localhost:5000"),
            # On the host Redpanda listens on 19092; inside Compose on redpanda:9092.
            kafka_bootstrap=os.environ.get("KAFKA_BOOTSTRAP", "localhost:19092"),
        )
