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


def test_status_waits_for_a_slow_platform(monkeypatch):
    """Run 4 lost 26 polls to a 10 s read timeout while replies took 10-20 s; the status call now waits 30 s."""
    from greenops import live
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    class H:
        def get(self, url, timeout=None, **kw):
            seen["timeout"] = timeout
            return R()

    lv = live.Live.__new__(live.Live)
    lv.a, lv.work, lv.http = {"key": "EXOtest", "secret": "s"}, "https://example.test/runs/r1/work/v1/status", H()
    assert lv.status() == {"ok": True}
    assert seen["timeout"] == (5, live.STATUS_TIMEOUT_S) and live.STATUS_TIMEOUT_S >= 25


def test_forecast_falls_back_to_this_runs_last_forecast():
    """Run 6: forecast requests timed out at hour 101, planning failed and a paused job stayed stopped past its
    deadline. A failed fetch now reuses the latest forecast this run published, shifted to the current hour."""
    from greenops import live
    lv = live.Live.__new__(live.Live)
    lv.fc_cache, lv.fc_last, lv.fc_failed = {}, {}, set()
    calls = {"n": 0}

    def fetch(area, now_h, horizon):
        calls["n"] += 1
        if now_h >= 10:
            raise TimeoutError("read timed out")
        return [float(int(now_h) + k) for k in range(horizon)]

    lv._fetch_forecast = fetch
    with contextlib.redirect_stdout(io.StringIO()):
        assert lv.forecast("AT", 7.0)[:2] == [7.0, 8.0]
        v = lv.forecast("AT", 12.0)
    assert len(v) == 24 and v[:3] == [12.0, 13.0, 14.0] and v[-1] == 30.0      # shifted, padded with the last value
    lv.fc_failed.add(("AT", 13))
    n = calls["n"]
    with contextlib.redirect_stdout(io.StringIO()):
        lv.forecast("AT", 13.0)
    assert calls["n"] == n, "an area whose prefetch failed this hour is not fetched a second time"


def test_safe_mode_starts_stopped_work_when_planning_fails():
    from greenops import live
    from greenops.planner import Planner
    from greenops.spec import load
    p = Planner(load(), lambda a, n: [100.0] * 24)
    st = {"now_h": 101.0, "workloads": [
        {"id": "w-11-dach-simulation", "final_output_delivered": False,
         "assignments": [{"vm_id": "a", "zone": "ch-dk-2", "state": "stopped"}]},
        {"id": "w-05-eu-render", "final_output_delivered": False,
         "assignments": [{"vm_id": "b", "zone": "fr-par-1", "state": "running"}]},
        {"id": "w-03-med-analysis", "final_output_delivered": True,
         "assignments": [{"vm_id": "c", "zone": "es-mad-1", "state": "stopped"}]}]}
    assert live.safe_actions(p, st) == [("start", "a", "w-11-dach-simulation")]


def test_actions_go_out_in_parallel_and_refusals_reach_the_planner():
    """Run 6: one action took 17.6 s and they were sent one by one. Six slow actions now take about one."""
    import time as _t
    from greenops import live
    from greenops.planner import Planner
    from greenops.spec import load

    class Slow:
        def act(self, kind, vm, zone):
            _t.sleep(0.3)
            if vm == "bad":
                raise RuntimeError("409 conflict")

    p = Planner(load(), lambda a, n: [100.0] * 24)
    acts = [("stop", f"vm{i}", "w-01-dach-research") for i in range(5)] + [("start", "bad", "w-02-ch-reporting")]
    t0 = _t.monotonic()
    live.act_parallel(Slow(), p, 50.0, acts, {})
    assert _t.monotonic() - t0 < 1.0
    assert [d for d in p.decisions if d["action"] == "rejected"] == [
        {"t": 50.0, "workload": "w-02-ch-reporting", "action": "rejected", "reason": "start refused: 409 conflict"}]


def test_limiter_under_concurrency(monkeypatch):
    """Live.prefetch shares one Limiter between up to 8 threads: 8 threads x 5 calls must each get their own
    slot, 1/50 s apart. The clock is frozen and the sleeps are recorded, so the check is exact on any OS
    (time.monotonic ticks every ~15.6 ms on Windows before Python 3.13)."""
    import threading
    import types
    from greenops import live

    slept, lock = [], threading.Lock()

    def sleep(d):
        with lock:
            slept.append(d)

    monkeypatch.setattr(live, "time", types.SimpleNamespace(monotonic=lambda: 100.0, sleep=sleep))
    lim = live.Limiter(per_s=50)
    threads = [threading.Thread(target=lambda: [lim.wait() for _ in range(5)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert sorted(slept) == pytest.approx([k / 50 for k in range(1, 40)])     # the first call does not wait


def test_status_signature_is_pinned():
    """Live.status computes an EXO2 HMAC-SHA256 signature over the request path and a fixed expires value.
    Verify the exact header shape and that recomputing the signature independently matches."""
    import base64
    import hashlib
    import hmac as hmac_mod
    import unittest.mock

    from greenops import live

    fixed_time = 1_700_000_000.0
    secret = "my-secret"
    key = "EXOtest"
    work_path = "/runs/r1/work/v1/status"
    expires = int(fixed_time) + 60

    seen_header = {}

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class H:
        def get(self, url, timeout=None, headers=None, **kw):
            if headers:
                seen_header["auth"] = headers.get("Authorization", "")
            return R()

    lv = live.Live.__new__(live.Live)
    lv.a = {"key": key, "secret": secret}
    lv.work = f"https://example.test{work_path}"
    lv.http = H()

    with unittest.mock.patch("greenops.live.time.time", return_value=fixed_time):
        result = lv.status()

    assert result == {"ok": True}
    assert "auth" in seen_header

    expected_sig = base64.b64encode(
        hmac_mod.new(secret.encode(), "\n".join(["GET " + work_path, "", "", "", str(expires)]).encode(),
                     hashlib.sha256).digest()
    ).decode()
    expected = f"EXO2-HMAC-SHA256 credential={key},expires={expires},signature={expected_sig}"
    assert seen_header["auth"] == expected


def test_safe_mode_only_starts_vms_in_legal_zones():
    """Defence in depth (review finding F5): safe mode never touches a VM whose zone is not legal for its
    workload. Zones are mapped to countries through the spec, as guard.is_allowed does."""
    from greenops import live
    from greenops.planner import Planner
    from greenops.spec import load
    p = Planner(load(), lambda a, n: [100.0] * 24)
    st = {"now_h": 50.0, "workloads": [
        {"id": "w-02-ch-reporting", "final_output_delivered": False, "assignments": [
            {"vm_id": "legal", "zone": "ch-dk-2", "state": "stopped"},
            {"vm_id": "illegal", "zone": "at-vie-1", "state": "stopped"},
            {"vm_id": "unknown", "zone": "xx-nowhere-1", "state": "stopped"}]}]}
    assert live.safe_actions(p, st) == [("start", "legal", "w-02-ch-reporting")]
