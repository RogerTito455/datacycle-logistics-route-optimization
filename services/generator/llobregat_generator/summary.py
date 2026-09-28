"""Sanity figures of one day of orders, against the company profile and the demand model."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import date

from llobregat_generator.orders import LOCAL_TZ, SIZES
from llobregat_generator.rules import (
    Recipient,
    Wave,
    minutes,
    weekday_business_share,
    weekday_same_day_share,
    zone_shares,
)
from llobregat_generator.zones import Polygon, in_polygons


def summarise(
    orders: Sequence[dict], company: dict, boundaries: dict[str, list[Polygon]] | None = None
) -> dict[str, object]:
    """Figures a reviewer compares with company.json and demand.json.

    Shares are shares of parcels unless the name says orders.
    """
    parcels = sum(o["parcels"] for o in orders)
    by_zone = Counter()
    for o in orders:
        by_zone[o["destination_zone_id"]] += o["parcels"]

    def share(predicate) -> float:
        return sum(o["parcels"] for o in orders if predicate(o)) / parcels if parcels else 0.0

    cutoff = minutes(company["hub"]["timetable"]["same_day_cutoff"])
    same_day = [o for o in orders if o["service_level"] == "same_day"]
    registered = [o["event_time"].astimezone(LOCAL_TZ) for o in same_day]
    figures: dict[str, object] = {
        "orders": len(orders),
        "parcels": parcels,
        "parcels_per_stop": parcels / len(orders) if orders else 0.0,
        "b2b_share": share(lambda o: o["customer_type"] == Recipient.BUSINESS),
        "same_day_share": share(lambda o: o["service_level"] == "same_day"),
        "same_day_orders": len(same_day),
        "same_day_after_cutoff": sum(
            t.date() != o["service_date"] or t.hour * 60 + t.minute >= cutoff
            for t, o in zip(registered, same_day, strict=True)
        ),
        "morning_wave_share": share(lambda o: o["wave"] == Wave.MORNING),
        "size_mix": {size: share(lambda o, s=size: o["parcel_size"] == s) for size in SIZES},
        "window_types": dict(Counter(o["window_type"] for o in orders)),
        "zone_share": {z["zone_id"]: by_zone[z["zone_id"]] / parcels if parcels else 0.0 for z in company["zones"]},
    }
    if boundaries is not None:
        inside = sum(
            in_polygons(boundaries[o["destination_zone_id"]], o["destination_lon"], o["destination_lat"])
            for o in orders
        )
        figures["inside_zone_boundary"] = inside / len(orders) if orders else 0.0
    return figures


def report(service_date: date, figures: dict, company: dict, demand: dict) -> str:
    """The figures as text, each next to what the seeds say."""
    volume = company["daily_volume"]
    b2b_model = weekday_business_share(demand)
    same_day_model = weekday_same_day_share(demand)
    mix = figures["size_mix"]
    lines = [
        f"{service_date} ({service_date:%A}): {figures['orders']} orders, {figures['parcels']} parcels, "
        f"{figures['parcels_per_stop']:.2f} parcels per stop",
        f"  business parcels   {figures['b2b_share']:.1%} (weekday model {b2b_model:.1%})",
        f"  same-day parcels   {figures['same_day_share']:.1%} (weekday model {same_day_model:.1%}), "
        f"{figures['same_day_orders']} orders, {figures['same_day_after_cutoff']} registered after the cut-off",
        f"  morning wave       {figures['morning_wave_share']:.1%} of parcels",
        f"  parcel mix         {mix['small']:.1%} / {mix['medium']:.1%} / {mix['large']:.1%} "
        f"(company.json {volume['parcel_mix']['small_pct']:.0f} / {volume['parcel_mix']['medium_pct']:.0f} / "
        f"{volume['parcel_mix']['large_pct']:.0f}%)",
        "  windows            " + ", ".join(f"{k} {v}" for k, v in sorted(figures["window_types"].items())),
    ]
    zone_share = zone_shares(company)
    worst = max(zone_share, key=lambda z: abs(figures["zone_share"][z] - zone_share[z]))
    lines.append(
        f"  zone shares        largest gap {worst}: {figures['zone_share'][worst]:.1%} "
        f"against {zone_share[worst]:.1%} in company.json"
    )
    if "inside_zone_boundary" in figures:
        lines.append(f"  inside the zone's official boundary: {figures['inside_zone_boundary']:.2%} of orders")
    return "\n".join(lines)
