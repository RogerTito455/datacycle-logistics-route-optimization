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

    @classmethod
    def from_env(cls) -> SimulatorSettings:
        return cls(
            base=Settings.from_env(),
            osrm_url=os.environ.get("OSRM_URL", "http://localhost:5000"),
        )
