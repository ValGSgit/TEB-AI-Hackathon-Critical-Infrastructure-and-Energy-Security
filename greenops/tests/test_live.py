"""greenops.live end to end against a fake platform serving the same API subset over the offline game."""
import contextlib
import json
import io
import sys

import pytest

from fake_platform import Fake


def test_live_loop_against_fake_platform(monkeypatch, tmp_path):
    f = Fake(seed=2, step_h=1.0)
    for k, v in dict(EXOSCALE_API_KEY="EXOtest", EXOSCALE_API_SECRET="secret", GREENOPS_CLOUD_ENDPOINT=f.cloud,
                     GREENOPS_GRID_ENDPOINT=f.grid_url, GREENOPS_GRID_SECRET="g",
                     NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "argv", ["live", "--config", str(tmp_path / "none.json"), "--poll", "0", "--rate", "1000", "--out", str(tmp_path)])
    from greenops import live
    with contextlib.redirect_stdout(io.StringIO()):
        live.main()
    assert not f.game.disqualified
    assert f.game.score()["delivered"] >= 14            # hourly ticks are coarse; real polling is every 12 min
    assert all(p.startswith("/runs/r1/") for _m, p in f.calls), "no request leaves the run prefix"
    assert (tmp_path / "decisions.jsonl").stat().st_size > 0


def test_endpoint_checks():
    from greenops.live import check_endpoint
    check_endpoint("https://example.test/runs/abc/cloud/v2")
    with pytest.raises(ValueError):
        check_endpoint("https://api.exoscale.com/runs/abc/cloud/v2")
    with pytest.raises(ValueError):
        check_endpoint("https://example.test/runs/other/cloud/at-vie-1/v2", "https://example.test/runs/abc/cloud/v2")


def test_probe_is_read_only_and_reads_env_file(monkeypatch, tmp_path):
    """--probe checks auth and response shapes without creating anything (the run clock stays off)."""
    f = Fake(seed=1)
    env = tmp_path / "greenops.env"
    env.write_text(f"# test\nEXOSCALE_API_KEY=EXOtest\nEXOSCALE_API_SECRET='s'\nGREENOPS_CLOUD_ENDPOINT={f.cloud}\n"
                   f"GREENOPS_GRID_ENDPOINT={f.grid_url}\nGREENOPS_GRID_SECRET=g\n")
    for k in ("EXOSCALE_API_KEY", "EXOSCALE_API_SECRET", "GREENOPS_CLOUD_ENDPOINT", "GREENOPS_GRID_ENDPOINT", "GREENOPS_GRID_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["live", "--probe", "--env-file", str(env), "--config", str(tmp_path / "none.json"),
                                      "--out", str(tmp_path)])
    from greenops import live
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        live.main()
    assert not any(m == "POST" for m, _p in f.calls) and not f.started
    s = json.loads((tmp_path / "probe.json").read_text())["summary"]
    assert s["zones_match_catalog"] and s["type_ids_equal_catalog_ids"] and s["run_state"] == "READY"
    assert s["forecast_points"] == {"forecast_AT_6h": 6, "forecast_AT_24h": 24}
    assert "s'" not in out.getvalue() and "EXOtest" not in out.getvalue()
