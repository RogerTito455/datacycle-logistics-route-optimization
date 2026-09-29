"""Which service zone an address belongs to, and the official boundaries of the zones.

The zones come from the company profile (company.json, prompt 001): nine zones made of Barcelona
districts and five neighbouring municipalities. Addresses carry the district code (Open Data BCN)
or the municipality (ICGC) they are registered in, and ZoneMap turns that into a zone by name, so
a zone renamed in company.json fails loudly instead of losing its addresses.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

BOUNDARIES_PATH = Path(__file__).parent / "zone_boundaries.geojson"

# The ten districts of Barcelona by the code taula-direle publishes (districte), named as the
# Open Data BCN district boundaries name them.
BARCELONA_DISTRICTS = {
    "01": "Ciutat Vella",
    "02": "Eixample",
    "03": "Sants-Montjuïc",
    "04": "Les Corts",
    "05": "Sarrià-Sant Gervasi",
    "06": "Gràcia",
    "07": "Horta-Guinardó",
    "08": "Nou Barris",
    "09": "Sant Andreu",
    "10": "Sant Martí",
}

Ring = list[tuple[float, float]]  # (lon, lat) points, first == last
Polygon = list[Ring]  # outer ring, then holes


def norm(text: str) -> str:
    """Lowercase letters and digits only, so "l'Hospitalet de Llobregat" matches "L'Hospitalet de Llobregat"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in text.lower() if ch.isalnum())


@dataclass(frozen=True)
class ZoneMap:
    """Zone of a Barcelona district code or of a neighbouring municipality, from company.json."""

    by_district: dict[str, str]
    by_municipality: dict[str, str]
    municipality_names: dict[str, str]

    @classmethod
    def from_company(cls, company: dict) -> ZoneMap:
        district_codes = {norm(name): code for code, name in BARCELONA_DISTRICTS.items()}
        by_district: dict[str, str] = {}
        by_municipality: dict[str, str] = {}
        names: dict[str, str] = {}
        for zone in company["zones"]:
            names[zone["zone_id"]] = zone["municipality"]
            if norm(zone["municipality"]) != "barcelona":
                by_municipality[norm(zone["municipality"])] = zone["zone_id"]
                continue
            for district in zone["districts"]:
                code = district_codes.get(norm(district))
                if code is None:
                    raise ValueError(f"{zone['zone_id']}: {district!r} is not a district of Barcelona")
                by_district[code] = zone["zone_id"]
        missing = sorted(set(BARCELONA_DISTRICTS) - set(by_district))
        if missing:
            raise ValueError(f"Barcelona districts that belong to no zone: {missing}")
        return cls(by_district, by_municipality, names)

    def for_district(self, district_code: str) -> str | None:
        return self.by_district.get(district_code)

    def for_municipality(self, municipality: str) -> str | None:
        return self.by_municipality.get(norm(municipality))

    def municipality(self, zone_id: str) -> str:
        """Municipality of a zone, spelt as in company.json."""
        return self.municipality_names[zone_id]


def load_boundaries(path: Path = BOUNDARIES_PATH) -> dict[str, list[Polygon]]:
    """Official boundary of every zone: Barcelona districts and municipalities, simplified."""
    collection = json.loads(path.read_text(encoding="utf-8"))
    boundaries: dict[str, list[Polygon]] = {}
    for feature in collection["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        boundaries[feature["properties"]["zone_id"]] = [
            [[(lon, lat) for lon, lat in ring] for ring in polygon] for polygon in polygons
        ]
    return boundaries


def in_polygons(polygons: list[Polygon], lon: float, lat: float) -> bool:
    """Even-odd ray casting over every ring, which also handles holes and multipolygons."""
    inside = False
    for polygon in polygons:
        for ring in polygon:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside
