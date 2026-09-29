"""The AI-generated seed files in services/generator/seed (prompts 001-004)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Seeds:
    company: dict
    fleet: dict
    drivers: dict
    demand: dict

    @classmethod
    def load(cls, seed_dir: Path) -> Seeds:
        def read(name: str) -> dict:
            return json.loads((seed_dir / f"{name}.json").read_text(encoding="utf-8"))

        return cls(company=read("company"), fleet=read("fleet"), drivers=read("drivers"), demand=read("demand"))
