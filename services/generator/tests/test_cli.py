"""The command line refuses what it should refuse before it touches the database."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from botocore.exceptions import EndpointConnectionError
from llobregat_generator import cli
from llobregat_generator.cli import main
from llobregat_generator.orders import LOCAL_TZ


def test_orders_refuses_a_date_after_today(capsys):
    tomorrow = datetime.now(LOCAL_TZ).date() + timedelta(days=1)
    assert main(["orders", "--date", tomorrow.isoformat()]) == 2
    assert "--allow-future" in capsys.readouterr().err


@pytest.mark.parametrize("count", ["0", "-3", "many"])
def test_pod_sample_refuses_a_count_that_is_not_above_zero(capsys, count):
    """A negative count would have sliced off the last orders and uploaded almost all of them."""
    with pytest.raises(SystemExit) as exit_:
        main(["pod-sample", "--date", "2026-09-28", "--count", count])
    assert exit_.value.code == 2
    assert "not a whole number above zero" in capsys.readouterr().err


def test_a_bucket_that_fails_is_an_error_message_not_a_traceback(capsys, monkeypatch):
    def unreachable(settings, args):
        raise EndpointConnectionError(endpoint_url="http://localhost:9000/bronze")

    monkeypatch.setattr(cli, "cmd_pod_sample", unreachable)
    assert main(["pod-sample", "--date", "2026-09-28"]) == 1
    assert "the RustFS bronze bucket at" in capsys.readouterr().err
