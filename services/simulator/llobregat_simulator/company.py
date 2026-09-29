"""The company as the planner and the simulator see it, read from the AI-generated seeds.

company.json (prompt 001) gives the hub, the zones with their stops per route and minutes per stop,
the vehicle types and the shifts; fleet.json (prompt 002) the vans and their home zones;
drivers.json (prompt 003) the drivers, their shift, the zones they know and the vehicle types they
are cleared for. The hub's geofence radius is a platform assumption kept in bronze.hubs
(migration 007); the command line reads it from there and passes it in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.reference import hub_id, shift_id
from llobregat_generator.rules import Recipient, Wave, delivery_waves
from llobregat_generator.seeds import Seeds

DEFAULT_GEOFENCE_M = 400  # bronze.hubs.geofence_radius_m, migration 007


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class Hub(Point):
    hub_id: str
    geofence_radius_m: int


@dataclass(frozen=True)
class Zone(Point):
    """A service zone; lat and lon are its centroid."""

    zone_id: str
    name: str
    stops_per_route: int
    minutes_per_stop: float
    difficulty: str
    preferred_types: tuple[str, ...]


@dataclass(frozen=True)
class VehicleType:
    type_id: str
    energy: str
    parcel_capacity: int
    consumption: float  # per 100 km, in consumption_unit
    consumption_unit: str  # kWh/100km, l/100km or kg/100km
    range_km: int
    sensors: tuple[str, ...]

    @property
    def energy_unit(self) -> str:
        """kWh, l or kg: what bronze.vehicle_telemetry.energy_unit holds."""
        return self.consumption_unit.split("/")[0]

    @property
    def tank(self) -> float:
        """Usable battery or tank, in energy_unit: the range at the rated consumption."""
        return self.range_km * self.consumption / 100


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    type: VehicleType
    home_zone_id: str
    runs_afternoon_wave: bool
    odometer_km: float
    battery_health_pct: float | None

    @property
    def capacity(self) -> int:
        return self.type.parcel_capacity


@dataclass(frozen=True)
class Driver:
    driver_id: str
    shift: str | None  # the wave of the driver's shift; None for the relief pool
    zones: frozenset[str]
    vehicle_types: frozenset[str]


@dataclass(frozen=True)
class Order(Point):
    """An order to deliver: one stop, as bronze.orders holds it."""

    order_id: str
    zone_id: str
    parcels: int
    parcel_size: str
    customer_type: str  # B2C or B2B
    wave: str
    window_type: str
    window_start: datetime
    window_end: datetime
    note_id: str | None = None

    @property
    def business(self) -> bool:
        return self.customer_type == Recipient.BUSINESS

    @classmethod
    def from_row(cls, row: Mapping) -> Order:
        """An order from a row of bronze.orders (publish.read_day)."""
        return cls(
            lat=row["destination_lat"],
            lon=row["destination_lon"],
            order_id=row["order_id"],
            zone_id=row["destination_zone_id"],
            parcels=row["parcels"],
            parcel_size=row["parcel_size"],
            customer_type=row["customer_type"],
            wave=row["wave"],
            window_type=row["window_type"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            note_id=row.get("note_id"),
        )


@dataclass(frozen=True)
class Company:
    hub: Hub
    zones: dict[str, Zone]
    vehicles: tuple[Vehicle, ...]
    drivers: tuple[Driver, ...]
    waves: dict[Wave, tuple[int, int]]  # delivery waves, minutes after midnight
    promised_window_min: int
    max_route_min: int
    break_min: dict[Wave, int]

    @classmethod
    def from_seeds(cls, seeds: Seeds, geofence_radius_m: int = DEFAULT_GEOFENCE_M) -> Company:
        company = seeds.company
        hub = company["hub"]
        types = {
            t["type_id"]: VehicleType(
                type_id=t["type_id"],
                energy=t["energy"],
                parcel_capacity=t["parcel_capacity"],
                consumption=t["consumption"]["value"],
                consumption_unit=t["consumption"]["unit"],
                range_km=t["range_km"],
                sensors=tuple(t["telemetry_sensors"]),
            )
            for t in company["fleet"]["vehicle_types"]
        }
        shifts = {s["name"]: s for s in company["drivers"]["shifts"]}
        return cls(
            hub=Hub(hub["lat"], hub["lon"], hub_id(hub), geofence_radius_m),
            zones={
                z["zone_id"]: Zone(
                    lat=z["centroid"]["lat"],
                    lon=z["centroid"]["lon"],
                    zone_id=z["zone_id"],
                    name=z["name"],
                    stops_per_route=z["stops_per_route"],
                    minutes_per_stop=z["minutes_per_stop"],
                    difficulty=z["delivery_difficulty"],
                    preferred_types=tuple(z["preferred_vehicle_type_ids"]),
                )
                for z in company["zones"]
            },
            vehicles=tuple(
                Vehicle(
                    vehicle_id=v["vehicle_id"],
                    type=types[v["type_id"]],
                    home_zone_id=v["home_zone_id"],
                    runs_afternoon_wave=v["runs_afternoon_wave"],
                    odometer_km=v["odometer_km"],
                    battery_health_pct=v["battery_state_of_health_pct"],
                )
                for v in seeds.fleet["vehicles"]
            ),
            drivers=tuple(
                Driver(
                    driver_id=d["driver_id"],
                    shift=shift_id(d["shift"]) if d["shift"] in shifts else None,
                    zones=frozenset(d["zone_knowledge"]),
                    vehicle_types=frozenset(d["qualified_vehicle_types"]),
                )
                for d in seeds.drivers["drivers"]
            ),
            waves=delivery_waves(company),
            promised_window_min=company["service_promise"]["promised_window_minutes"],
            max_route_min=company["drivers"]["max_route_duration_minutes"],
            break_min={Wave(shift_id(name)): s["break_minutes"] for name, s in shifts.items()},
        )

    def fleet(self, wave: Wave) -> list[Vehicle]:
        """The vans of a wave: the whole fleet in the morning, the afternoon vans of the fleet register after."""
        return [v for v in self.vehicles if wave == Wave.MORNING or v.runs_afternoon_wave]

    def crew(self, wave: Wave) -> list[Driver]:
        """The drivers of the wave's shift."""
        return [d for d in self.drivers if d.shift == wave]


def local(service_date: date, minute_of_day: float) -> datetime:
    """A moment of the service date in Barcelona, from minutes after midnight."""
    return datetime.combine(service_date, time(), LOCAL_TZ) + timedelta(minutes=minute_of_day)
