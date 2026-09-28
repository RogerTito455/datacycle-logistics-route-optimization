"""Assets, schedules and sensors of the platform.

Milestone M1 only has the platform health check. Loaders, dbt models and the
optimizer are added as their issues land.
"""

import dagster as dg

from llobregat_pipelines.platform_health import platform_health

platform_health_every_5_min = dg.ScheduleDefinition(
    name="platform_health_every_5_min",
    target=dg.AssetSelection.assets(platform_health),
    cron_schedule="*/5 * * * *",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

defs = dg.Definitions(
    assets=[platform_health],
    schedules=[platform_health_every_5_min],
)
