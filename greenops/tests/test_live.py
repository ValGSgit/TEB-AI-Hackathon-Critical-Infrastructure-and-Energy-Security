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
    monkeypatch.setattr(sys, "argv", ["live", "--env-file", str(tmp_path / "none.env"), "--config", str(tmp_path / "none.json"), "--poll", "0", "--rate", "1000", "--out", str(tmp_path)])
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


def test_loop_survives_a_bad_status_reply(monkeypatch, tmp_path):
    """A malformed reply (like the timestamp that crashed run 1) is logged and skipped, not fatal."""
    f = Fake(seed=3, step_h=1.0)
    for k, v in dict(EXOSCALE_API_KEY="EXOtest", EXOSCALE_API_SECRET="s", GREENOPS_CLOUD_ENDPOINT=f.cloud,
                     GREENOPS_GRID_ENDPOINT=f.grid_url, GREENOPS_GRID_SECRET="g").items():
        monkeypatch.setenv(k, v)
    real, calls = f.status, []

    def flaky():
        calls.append(1)
        body = real()
        if len(calls) == 5:
            body["virtual_time"] = "not a time"
        return body

    monkeypatch.setattr(f, "status", flaky)
    monkeypatch.setattr(sys, "argv", ["live", "--env-file", str(tmp_path / "none.env"), "--config", str(tmp_path / "none.json"),
                                      "--poll", "0", "--rate", "1000", "--out", str(tmp_path)])
    from greenops import live
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        live.main()
    assert '"warning": "status failed: ValueError' in out.getvalue()
    assert f.game.score()["delivered"] >= 14 and not f.game.disqualified


@pytest.mark.parametrize("run", ["r1", "other"])
def test_work_endpoint_must_belong_to_the_run(monkeypatch, tmp_path, run):
    """GREENOPS_WORK_ENDPOINT (given by the portal since run 3) is checked against the cloud run, not trusted."""
    f = Fake(seed=1)
    for k, v in dict(EXOSCALE_API_KEY="EXOtest", EXOSCALE_API_SECRET="s", GREENOPS_CLOUD_ENDPOINT=f.cloud,
                     GREENOPS_GRID_ENDPOINT=f.grid_url, GREENOPS_GRID_SECRET="g",
                     GREENOPS_WORK_ENDPOINT=f.cloud.replace("/runs/r1/", f"/runs/{run}/").removesuffix("/cloud/v2") + "/work/v1",
                     NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "argv", ["live", "--probe", "--env-file", str(tmp_path / "none.env"),
                                      "--config", str(tmp_path / "none.json"), "--out", str(tmp_path)])
    from greenops import live
    with contextlib.redirect_stdout(io.StringIO()):
        if run == "r1":
            live.main()
        else:
            with pytest.raises(ValueError, match="Work endpoint"):
                live.main()
    assert not any(m == "POST" for m, _p in f.calls)


def test_one_forecast_fetch_per_area_per_hour_and_deletes_first(monkeypatch, tmp_path):
    """At 720x a wall second is 0.2 simulated hours, so the loop must not repeat forecast fetches (the rescue
    pass re-plans up to three times an hour) and must delete delivered VMs before anything slow."""
    f = Fake(seed=2, step_h=1.0, forecast_delay_s=0.02)
    for k, v in dict(EXOSCALE_API_KEY="EXOtest", EXOSCALE_API_SECRET="secret", GREENOPS_CLOUD_ENDPOINT=f.cloud,
                     GREENOPS_GRID_ENDPOINT=f.grid_url, GREENOPS_GRID_SECRET="g",
                     NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "argv", ["live", "--env-file", str(tmp_path / "none.env"), "--config", str(tmp_path / "none.json"),
                                      "--poll", "0", "--rate", "1000", "--out", str(tmp_path)])
    from greenops import live
    with contextlib.redirect_stdout(io.StringIO()):
        live.main()
    areas = {s.area for s in f.spec.sites.values()}
    fetches = [p for m, p in f.calls if "carbon-intensity/forecast" in p]
    polls = [p for m, p in f.calls if p.endswith("/work/v1/status")]
    assert len(fetches) <= len(areas) * (len(polls) + 1), (len(fetches), len(polls))
    assert f.game.score()["delivered"] >= 14 and not f.game.vms, "every VM deleted at the end"
