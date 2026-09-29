"""The self-hosted OSRM of the stack: travel-time matrices and route geometry on the real road network.

The planner orders stops on the duration matrix of /table. The simulator drives the vans along the
geometry of /route, segment by segment, at the speed OSRM gives each segment.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass

from llobregat_simulator.company import Point

TIMEOUT_S = 60
# /table fills a pair OSRM cannot route (a point snapped to a road cut off from the rest) with the
# straight-line distance at this speed, in metres per second, instead of leaving it empty.
FALLBACK_SPEED_MS = 5.0


class OsrmError(RuntimeError):
    """OSRM did not answer, or answered with something other than Ok."""


@dataclass(frozen=True)
class Leg:
    """The road from one waypoint to the next: points and, between consecutive points, metres and seconds."""

    coordinates: list[tuple[float, float]]  # (lon, lat), one more than segments
    distances_m: list[float]
    durations_s: list[float]

    @property
    def distance_m(self) -> float:
        return sum(self.distances_m)

    @property
    def duration_s(self) -> float:
        return sum(self.durations_s)


@dataclass(frozen=True)
class Route:
    """The road through a list of waypoints: one leg per pair, and where each waypoint snapped to a road."""

    legs: list[Leg]
    snapped: list[tuple[float, float]]  # (lon, lat) of every waypoint on the road network


def _coordinates(points: Sequence[Point]) -> str:
    return ";".join(f"{p.lon:.6f},{p.lat:.6f}" for p in points)


class Osrm:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _get(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.url}/{path}", timeout=TIMEOUT_S) as response:
                reply = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OsrmError(f"OSRM at {self.url} did not answer: {exc}") from exc
        if reply.get("code") != "Ok":
            raise OsrmError(f"OSRM replied {reply.get('code')}: {reply.get('message', '')}")
        return reply

    def table(self, points: Sequence[Point]) -> tuple[list[list[float]], list[list[float]]]:
        """Durations in seconds and distances in metres between every pair of points."""
        reply = self._get(
            f"table/v1/driving/{_coordinates(points)}?annotations=duration,distance&fallback_speed={FALLBACK_SPEED_MS}"
        )
        return reply["durations"], reply["distances"]

    def route(self, points: Sequence[Point]) -> Route:
        """The fastest road through the points in their order, with the geometry of every leg.

        OSRM's per-segment durations leave out turn and traffic-light penalties, which only the leg
        total includes, so each leg's segments are scaled to add up to it.
        """
        reply = self._get(
            f"route/v1/driving/{_coordinates(points)}"
            "?overview=full&geometries=geojson&annotations=distance,duration&steps=false&continue_straight=false"
        )
        route = reply["routes"][0]
        coordinates = [tuple(c) for c in route["geometry"]["coordinates"]]
        legs, offset = [], 0
        for leg in route["legs"]:
            distances, durations = leg["annotation"]["distance"], leg["annotation"]["duration"]
            segment_total = sum(durations)
            scale = leg["duration"] / segment_total if segment_total > 0 else 1.0
            legs.append(
                Leg(
                    coordinates=coordinates[offset : offset + len(distances) + 1],
                    distances_m=list(distances),
                    durations_s=[d * scale for d in durations],
                )
            )
            offset += len(distances)
        return Route(legs=legs, snapped=[tuple(w["location"]) for w in reply["waypoints"]])
