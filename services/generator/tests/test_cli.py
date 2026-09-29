"""The command line refuses what it should refuse before it touches the database."""

from __future__ import annotations

from datetime import datetime, timedelta

from llobregat_generator.cli import main
from llobregat_generator.orders import LOCAL_TZ


def test_orders_refuses_a_date_after_today(capsys):
    tomorrow = datetime.now(LOCAL_TZ).date() + timedelta(days=1)
    assert main(["orders", "--date", tomorrow.isoformat()]) == 2
    assert "--allow-future" in capsys.readouterr().err
