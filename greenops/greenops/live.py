"""Run the planner against a live GreenOps simulation run.

    python -m greenops.live --probe --out .local/probe    # read-only checks; creates nothing, clock stays off
    python -m greenops.live --out .local/run1              # the run itself

Credentials never live in the repo. They come from the environment, from an env file
(--env-file, default .local/greenops.env, git-ignored; see credentials.example.env), or from the
run's downloaded CLI config (greenops-exo.json, git-ignored): EXOSCALE_API_KEY, EXOSCALE_API_SECRET,
GREENOPS_CLOUD_ENDPOINT, and for the grid API GREENOPS_GRID_ENDPOINT and GREENOPS_GRID_SECRET.

Endpoint checks and the run-only HTTP adapter follow the organizers' starter kit
(examples/python/static.py, work.py, grid.py): no request may leave this run's URL prefix.
The process writes its decision log and status samples to --out (default /tmp/greenops-run).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from exoscale.api.v2 import Client

from .guard import ResidencyViolation, check_placement
from .planner import Planner
from .spec import load, to_h

TERMINAL = {"COMPLETED", "INVALIDATED", "UNAVAILABLE"}
STATUS_TIMEOUT_S = 30           # read timeout for the work status (connect timeout: 5 s)


# ---------------------------------------------------------------- account and run-scoped HTTP
def check_endpoint(value, reference=None):
    u = urlparse(value)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("Expected a challenge run URL")
    parts = u.path.strip("/").split("/")
    if len(parts) not in {4, 5} or parts[0] != "runs" or parts[2] != "cloud" or parts[-1] != "v2":
        raise ValueError("Cloud endpoint must be /runs/{id}/cloud[/zone]/v2")
    if u.hostname == "exoscale.com" or u.hostname.endswith(".exoscale.com"):
        raise ValueError("Use challenge endpoints only")
    if reference:
        r = urlparse(reference)
        if (u.scheme, u.netloc) != (r.scheme, r.netloc) or parts[1] != r.path.strip("/").split("/")[1]:
            raise ValueError("Discovered endpoint escaped the configured run")
    return value


ENV_ALIASES = {"API_KEY": "EXOSCALE_API_KEY", "API_SECRET": "EXOSCALE_API_SECRET", "CLOUD_ENDPOINT": "GREENOPS_CLOUD_ENDPOINT",
               "GRID_ENDPOINT": "GREENOPS_GRID_ENDPOINT", "GRID_SECRET": "GREENOPS_GRID_SECRET",
               "WORK_ENDPOINT": "GREENOPS_WORK_ENDPOINT"}
ENV_FILES = (".local/greenops.env", ".env", "../.env")


def load_env_file(path: str) -> None:
    """KEY=VALUE lines into os.environ (short names like GRID_SECRET accepted); variables already set win.
    Values are never printed."""
    if not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().removeprefix("export ")
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(ENV_ALIASES.get(k.strip(), k.strip()), v.strip().strip('"').strip("'"))


def find_config(path: str | None) -> str | None:
    """--config, else greenops-exo.json, else the single downloaded greenops-exo-<run>.json, here or one level up."""
    if path:
        return path
    for d in (Path.cwd(), Path.cwd().parent):
        if (d / "greenops-exo.json").is_file():
            return str(d / "greenops-exo.json")
        found = sorted(d.glob("greenops-exo-*.json"))
        if len(found) > 1:
            raise ValueError(f"several run configs in {d}; pick one with --config")
        if found:
            return str(found[0])
    return None


def grid_endpoint(cloud_endpoint: str) -> str:
    """The run's grid URL sits next to its cloud URL: /runs/{id}/grid/v4 on the same host."""
    return os.environ.get("GREENOPS_GRID_ENDPOINT") or cloud_endpoint.split("/cloud/")[0] + "/grid/v4"


def read_account(path: str | None) -> dict:
    if path and Path(path).exists():
        config = json.loads(Path(path).read_text())
        account = next(a for a in config["accounts"] if a["name"] == config["defaultaccount"])
    else:
        account = {"key": os.environ["EXOSCALE_API_KEY"], "secret": os.environ["EXOSCALE_API_SECRET"],
                   "endpoint": os.environ["GREENOPS_CLOUD_ENDPOINT"]}
    check_endpoint(account["endpoint"])
    return account


class RunOnlyAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, root, prefix=None):
        self.root = urlparse(root)
        self.prefix = prefix or self.root.path.rsplit("/v2", 1)[0] + "/"
        super().__init__()

    def send(self, request, **kwargs):
        target = urlparse(request.url)
        if (target.scheme, target.netloc) != (self.root.scheme, self.root.netloc) or not target.path.startswith(self.prefix):
            raise ValueError("Request escaped the configured cloud run")
        return super().send(request, **kwargs)


class Limiter:
    """Client-side pacing under the published limits (cloud+grid 20/s, work 5/s)."""

    def __init__(self, per_s: float):
        self.gap, self.next, self.lock = 1.0 / per_s, 0.0, threading.Lock()

    def wait(self):
        with self.lock:                       # forecasts are fetched from several threads at once
            now = time.monotonic()
            slot = max(now, self.next)
            self.next = slot + self.gap
        if slot > now:
            time.sleep(slot - now)


# ---------------------------------------------------------------- the three APIs
class Live:
    def __init__(self, account: dict, grid_endpoint: str, grid_secret: str, spec, rate: float = 12):
        self.a, self.spec = account, spec
        self.api = Limiter(rate)
        self.zones = {z["name"]: check_endpoint(z["api-endpoint"], account["endpoint"])
                      for z in self._client(account["endpoint"]).list_zones()["zones"]}
        self.clients = {z: self._client(url) for z, url in self.zones.items()}
        cloud, grid = urlparse(account["endpoint"]), urlparse(grid_endpoint.rstrip("/"))
        if (grid.scheme, grid.netloc, grid.path) != (cloud.scheme, cloud.netloc, cloud.path.split("/cloud/")[0] + "/grid/v4"):
            raise ValueError("Grid endpoint must belong to this cloud run")
        self.grid, self.grid_secret = grid_endpoint.rstrip("/"), grid_secret
        self.work = account["endpoint"].removesuffix("/cloud/v2") + "/work/v1/status"
        given = os.environ.get("GREENOPS_WORK_ENDPOINT", "").rstrip("/").removesuffix("/status")
        if given and given + "/status" != self.work:     # e.g. a fresh .env next to an old run config
            raise ValueError("Work endpoint must belong to this cloud run")
        self.http = requests.Session()          # keep-alive for work + grid, locked to /runs/{id}/
        guard = RunOnlyAdapter(account["endpoint"], prefix=cloud.path.split("/cloud/")[0] + "/")
        self.http.mount("http://", guard)
        self.http.mount("https://", guard)
        self.types, self.template = {}, {}
        self.fc_cache = {}                    # (area, hour, horizon) -> values: forecasts change at most hourly
        self.fc_last = {}                     # area -> (hour, values) of the latest forecast received
        self.fc_failed = set()                # (area, hour) whose prefetch failed: use fc_last instead
        self.vm_zone = {}

    def _client(self, url):
        c = Client(self.a["key"], self.a["secret"], url=check_endpoint(url, self.a["endpoint"]))
        guard = RunOnlyAdapter(self.a["endpoint"])
        c.http_client.mount("http://", guard)
        c.http_client.mount("https://", guard)
        c.http_client.max_redirects = 0
        return c

    # ---- work status (EXO2 HMAC over the full prefixed path)
    def status(self):
        expires = str(int(time.time()) + 60)
        path = urlparse(self.work).path
        sig = base64.b64encode(hmac.new(self.a["secret"].encode(), "\n".join(["GET " + path, "", "", "", expires]).encode(),
                                        hashlib.sha256).digest()).decode()
        # run 4: the platform's reply took 10-20 s at times, so a 10 s read timeout threw away replies that were
        # about to arrive and started over; waiting longer is the faster way to learn the state
        r = self.http.get(self.work, timeout=(5, STATUS_TIMEOUT_S), allow_redirects=False, headers={
            "Authorization": f'EXO2-HMAC-SHA256 credential={self.a["key"]},expires={expires},signature={sig}'})
        if r.status_code == 429:
            time.sleep(min(10, max(1, int(r.headers.get("Retry-After", "1")))))
            return None
        r.raise_for_status()
        return r.json()

    # ---- grid forecasts of this run only
    def forecast(self, area: str, now_h: float, horizon: int = 24) -> list:
        key = (area, int(now_h), horizon)
        if key not in self.fc_cache:
            self.fc_cache = {k: v for k, v in self.fc_cache.items() if k[1] >= int(now_h) - 1}
            try:
                if (area, int(now_h)) in self.fc_failed and area in self.fc_last:
                    raise TimeoutError("failed in this hour's prefetch")      # do not wait for it a second time
                self._store(key, self._fetch_forecast(area, now_h, horizon))
            except Exception as e:
                vals = self._stale(area, now_h, horizon)
                if vals is None:
                    raise
                print(json.dumps({"warning": f"forecast for {area} failed ({type(e).__name__}); using this run's "
                                             f"forecast from hour {self.fc_last[area][0]}"}))
                return vals
        return self.fc_cache[key]

    def _store(self, key, vals):
        self.fc_cache[key] = vals
        self.fc_last[key[0]] = (key[1], vals)

    def _stale(self, area: str, now_h: float, horizon: int):
        """The latest forecast this run published for the area, shifted to now (run 6: forecast requests timed out
        and planning stopped, which left a paused job stopped past its deadline). Still only this run's forecast."""
        if area not in self.fc_last:
            return None
        h, vals = self.fc_last[area]
        tail = vals[max(0, int(now_h) - h):]
        return (list(tail) + [tail[-1] if tail else vals[-1]] * horizon)[:horizon]

    def prefetch(self, areas, now_h: float) -> None:
        """Fetch every area's forecast for this hour in parallel, so the hourly re-plan waits for one round trip
        instead of eight in a row (at 720x each wall second is 0.2 simulated hours)."""
        todo = [a for a in areas if (a, int(now_h), 24) not in self.fc_cache]

        def one(a):
            try:
                return self._fetch_forecast(a, now_h, 24)
            except Exception:
                return None                   # forecast() retries it once and falls back to the last one
        with ThreadPoolExecutor(max_workers=min(8, len(todo) or 1)) as ex:
            for a, vals in zip(todo, ex.map(one, todo)):
                if vals is not None:
                    self._store((a, int(now_h), 24), vals)
                else:
                    self.fc_failed.add((a, int(now_h)))

    def _fetch_forecast(self, area: str, now_h: float, horizon: int) -> list:
        self.api.wait()
        r = self.http.get(self.grid + "/carbon-intensity/forecast", timeout=20, allow_redirects=False,
                         params={"zone": area, "horizonHours": horizon}, headers={"auth-token": self.grid_secret})
        r.raise_for_status()
        pts = {int(round(to_h(p["datetime"]))): float(p["carbonIntensity"]) for p in r.json()["forecast"]}
        if not pts:
            raise ValueError(f"empty forecast for {area}")
        vals = []
        for h in range(int(now_h), int(now_h) + horizon):     # align to whole hours from now; fill gaps
            vals.append(pts[h] if h in pts else (vals[-1] if vals else pts[min(pts, key=lambda k: abs(k - h))]))
        return vals

    # ---- cloud actions
    def _type_id(self, zone, profile_id):
        info = self.spec.pinfo[profile_id]
        key = (zone, profile_id)
        if key not in self.types:
            self.api.wait()
            ts = self.clients[zone].list_instance_types()["instance-types"]
            hit = [t for t in ts if t["id"] == profile_id] or [t for t in ts if t.get("family") == info.family and t.get("size") == info.size]
            if not hit:
                raise ValueError(f"no instance type {info.family}.{info.size} in {zone}")
            self.types[key] = hit[0]["id"]
        return self.types[key]

    def _template(self, zone):
        if zone not in self.template:
            self.api.wait()
            self.template[zone] = self.clients[zone].list_templates(visibility="public")["templates"][0]["id"]
        return self.template[zone]

    def create(self, workload, zone, profile_id, name) -> str:
        check_placement(workload, next(z for z in self.spec.zones if z.id == zone))   # last line of defence
        c = self.clients[zone]
        self.api.wait()
        same = [v for v in c.list_instances()["instances"] if v["name"] == name]   # idempotent after a lost reply
        if len(same) > 1:
            raise ValueError(f"duplicate VM name {name}; inspect the run before retrying")
        if same:
            vm_id = same[0]["id"]
        else:
            binding = {"greenops": {"schema_version": "1.0", "workload_id": workload.id}}
            self.api.wait()
            op = c.create_instance(name=name, instance_type={"id": self._type_id(zone, profile_id)},
                                   template={"id": self._template(zone)}, disk_size=10,
                                   user_data=base64.b64encode(json.dumps(binding).encode()).decode())
            vm_id = op["reference"]["id"]
        self.vm_zone[vm_id] = zone
        return vm_id

    def existing(self) -> dict:
        """vm id -> instance-type id for VMs already in this run (after a controller restart)."""
        out = {}
        for zone, c in self.clients.items():
            self.api.wait()
            for v in c.list_instances().get("instances", []):
                t = v.get("instance-type") or {}
                if t.get("id"):
                    out[v["id"]] = t["id"]
                    self.vm_zone[v["id"]] = zone
        return out

    def act(self, kind, vm_id, zone):
        c = self.clients[zone or self.vm_zone[vm_id]]
        self.api.wait()
        {"stop": c.stop_instance, "start": c.start_instance, "delete": c.delete_instance}[kind](id=vm_id)


# ---------------------------------------------------------------- control loop
def safe_actions(planner, st: dict) -> list:
    """Planning failed: start every stopped VM of an unfinished workload. Running costs some carbon; staying
    stopped while the platform is unreachable can cost the deadline (and the 5,000-point bonus)."""
    acts = []
    for r in st["workloads"]:
        if r["final_output_delivered"]:
            continue
        stopped = [a["vm_id"] for a in r["assignments"] if a["state"] == "stopped"]
        acts += [("start", v, r["id"]) for v in stopped]
        if stopped:
            planner._log(st["now_h"], r["id"], "run", "safe mode: planning failed, so unfinished work runs")
    return acts


def view(raw: dict) -> dict:
    """Work-status response -> the planner's view (same shape as game.Game.status())."""
    vt = raw.get("virtual_time")
    rows = []
    for w in raw["workloads"]:
        rows.append({"id": w["id"], "required_work": float(w["required_work"]), "completed_work": float(w["completed_work"]),
                     "lost_work": float(w.get("lost_work") or 0), "output_ready_at": w.get("output_ready_at"),
                     "final_output_delivered": bool(w["final_output_delivered"]),
                     "assignments": [{"vm_id": a["vm_id"], "zone": a["zone"], "state": a["state"]} for a in w["assignments"]]})
    return {"now_h": to_h(vt) if vt else 0.0, "state": raw["state"], "qualification": raw.get("qualification"), "workloads": rows}


def probe(live: Live, spec, out: Path) -> dict:
    """Read-only look at the real API: no create, so the run clock does not start.
    Writes the raw responses to out/probe.json (run data: keep it out of git) and returns a summary."""
    raw = {"status": live.status()}
    zone = next(iter(live.clients))
    live.api.wait()
    types = live.clients[zone].list_instance_types()["instance-types"]
    live.api.wait()
    raw["templates"] = live.clients[zone].list_templates(visibility="public")["templates"][:3]
    raw["instance_types"] = {zone: types}
    area = sorted({s.area for s in spec.sites.values()})[0]
    for hz in ((6, 24) if live.grid_secret else ()):
        live.api.wait()
        r = live.http.get(live.grid + "/carbon-intensity/forecast", timeout=20, allow_redirects=False,
                          params={"zone": area, "horizonHours": hz}, headers={"auth-token": live.grid_secret})
        raw[f"forecast_{area}_{hz}h"] = {"http": r.status_code, "body": r.json() if r.ok else r.text[:500]}
    catalog = {p.id for p in spec.profiles if p.available_in(zone)}
    ids = {t["id"] for t in types}
    st = raw["status"] or {}
    summary = {"zones": sorted(live.zones), "zones_match_catalog": sorted(live.zones) == sorted(z.id for z in spec.zones),
               "run_state": st.get("state"), "speed_multiplier": st.get("speed_multiplier"),
               "virtual_time": st.get("virtual_time"), "workloads": len(st.get("workloads", [])),
               "work_status_fields": sorted(st.get("workloads", [{}])[0]) if st.get("workloads") else [],
               f"instance_types_in_{zone}": len(types), "type_ids_equal_catalog_ids": ids == catalog,
               "type_fields": sorted(types[0]) if types else [], "templates": [t.get("name") for t in raw["templates"]],
               "forecast_points": {k: len(v["body"].get("forecast", [])) if isinstance(v["body"], dict) else v["http"]
                                   for k, v in raw.items() if k.startswith("forecast_")},
               "forecast_point_fields": next((sorted(v["body"]["forecast"][0]) for k, v in raw.items() if k.startswith("forecast_")
                                              and isinstance(v["body"], dict) and v["body"].get("forecast")), [])}
    if not live.grid_secret:
        summary["forecast_points"] = "skipped: GREENOPS_GRID_SECRET not set"
    elif raw["status"]:
        summary["plan"] = dry_plan(spec, live.forecast, view(raw["status"]))
    (out / "probe.json").write_text(json.dumps({"summary": summary, "raw": raw}, indent=1), encoding="utf-8")
    return summary


def dry_plan(spec, forecast, st: dict) -> dict:
    """The plan the planner would make now, from this run's forecasts, with every zone residency-checked.
    No cloud call is made: nothing is created."""
    pl = Planner(spec, forecast)
    first = pl.bootstrap(st)
    zones = {z.id: z for z in spec.zones}
    rows, illegal = [], []
    for wid, slot in sorted(pl.plan.items(), key=lambda kv: kv[1].start):
        w, z = pl.W[wid], zones[slot.placement.zone_id]
        try:
            check_placement(w, z)
        except ResidencyViolation:
            illegal.append(wid)
        rows.append(f"{wid:24s} {z.id:9s} ({z.country}; allowed {','.join(sorted(w.allowed_countries))}) "
                    f"{spec.pinfo[slot.placement.profile_id].family}.{spec.pinfo[slot.placement.profile_id].size} "
                    f"x{slot.placement.workers} block {slot.start}-{slot.end}h run {len(slot.run)}h")
    return {"planned": f"{len(pl.plan)}/{len(spec.workloads)}", "all_legal": not illegal, "illegal": illegal,
            "first_create": f"{first[0][1]} in {first[0][2]} x{len(first)}" if first else None, "slots": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.environ.get("GREENOPS_CONFIG"),
                    help="run CLI config (default: greenops-exo.json or greenops-exo-<run>.json here or one level up)")
    ap.add_argument("--out", default=os.environ.get("GREENOPS_OUT", "/tmp/greenops-run"))
    ap.add_argument("--poll", type=float, default=1.0, help="wall seconds between status polls (keep >= 1 against the real API)")
    ap.add_argument("--rate", type=float, default=12, help="cloud+grid requests per second (published limit 20)")
    ap.add_argument("--max-wall", type=float, default=None,
                    help="stop after this many wall seconds (default: none; practice runs can be paused or change speed)")
    ap.add_argument("--env-file", default=os.environ.get("GREENOPS_ENV_FILE"),
                    help="credentials file (default: .local/greenops.env, then .env here or one level up)")
    ap.add_argument("--probe", action="store_true", help="read-only API checks; creates nothing")
    a = ap.parse_args()
    for f in ([a.env_file] if a.env_file else ENV_FILES):
        load_env_file(f)
    for short, full in ENV_ALIASES.items():         # e.g. docker run --env-file .env with short names
        if os.environ.get(short) and not os.environ.get(full):
            os.environ[full] = os.environ[short]

    spec = load()
    account = read_account(find_config(a.config))
    secret = os.environ.get("GREENOPS_GRID_SECRET", "")
    if not secret and not a.probe:
        raise ValueError("GREENOPS_GRID_SECRET is missing (portal: API credentials; put it in .local/greenops.env)")
    live = Live(account, grid_endpoint(account["endpoint"]), secret, spec, a.rate)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.probe:
        print(json.dumps(probe(live, spec, out), indent=1))
        return
    planner = Planner(spec, live.forecast)
    planner.vm_profile.update({k: v for k, v in live.existing().items() if v in planner.P})
    log = open(out / "decisions.jsonl", "a", encoding="utf-8")
    samples = open(out / "status.jsonl", "a", encoding="utf-8")
    names, seen, last_sample = {}, 0, -1
    t_end = None if a.max_wall is None else time.monotonic() + a.max_wall
    W = {w.id: w for w in spec.workloads}
    areas = sorted({site.area for site in spec.sites.values()})

    while t_end is None or time.monotonic() < t_end:
        t0 = time.monotonic()
        try:
            raw = live.status()
            if raw is None:
                continue
            st = view(raw)
        except Exception as e:                      # any surprise: keep managing the VMs, never exit mid-run
            print(json.dumps({"warning": f"status failed: {type(e).__name__}: {str(e)[:200]}"}))
            time.sleep(0.5)                         # retry soon: at 720x every wall second is 0.2 simulated hours
            continue
        if st["qualification"] == "DISQUALIFIED" or st["state"] in TERMINAL:
            print(json.dumps({"end": st["state"], "qualification": st["qualification"], "t": st["now_h"]}))
            break
        if int(st["now_h"]) != last_sample:
            samples.write(json.dumps(raw) + "\n")
            samples.flush()
            last_sample = int(st["now_h"])
        where = {a["vm_id"]: a["zone"] for r in st["workloads"] for a in r["assignments"]}
        # deletes first: a delivered job's VMs only draw idle power, and nothing below may hold them up
        for r in st["workloads"]:
            if r["final_output_delivered"] and r["assignments"]:
                ids = [x["vm_id"] for x in r["assignments"]]
                for vm in ids:
                    try:
                        live.act("delete", vm, where.get(vm))
                    except Exception as e:              # retried next poll: the status still lists the VM
                        planner.rejected(st["now_h"], ("delete", vm, r["id"]), str(e)[:200])
                planner._log(st["now_h"], r["id"], "delete", "final output delivered; deleting ends idle draw", vms=ids)
                r["assignments"] = []
        if int(st["now_h"]) != planner._plan_hour:      # the planner re-plans this poll: fetch forecasts in parallel
            try:
                live.prefetch(areas, st["now_h"])
            except Exception as e:                      # the planner fetches what is missing itself
                print(json.dumps({"warning": f"forecast prefetch failed: {type(e).__name__}: {str(e)[:200]}"}))
        t1 = time.monotonic()
        try:
            actions = planner.bootstrap(st) if st["state"] == "READY" else planner.decide(st)
        except ResidencyViolation:
            raise                                   # never happens by construction; stop hard if it does
        except Exception as e:                      # e.g. no forecast at all: never leave unfinished work stopped
            print(json.dumps({"warning": f"planning failed: {type(e).__name__}: {str(e)[:200]}"}))
            actions = safe_actions(planner, st)
        t2 = time.monotonic()
        for act in actions:
            try:
                if act[0] == "create":
                    _, wid, zone, prof, i = act
                    n = names[(wid, i)] = names.get((wid, i), -1) + 1
                    vm = live.create(W[wid], zone, prof, f"gops-{wid}-{i}-{n}")
                    planner.vm_profile[vm] = prof
                else:
                    live.act(act[0], act[1], where.get(act[1]))
            except ResidencyViolation:
                raise                                   # never happens by construction; stop hard if it does
            except Exception as e:                      # quota, transient API errors: re-planned next tick
                planner.rejected(st["now_h"], act, str(e)[:200])
        t3 = time.monotonic()
        if t3 - t0 > 2.0:      # at 720x one wall second is 0.2 simulated hours: say where a slow poll went
            print(json.dumps({"slow_poll_s": round(t3 - t0, 2), "status_s": round(t1 - t0, 2), "plan_s": round(t2 - t1, 2),
                              "act_s": round(t3 - t2, 2), "actions": len(actions), "t": round(st["now_h"], 2)}))
        for d in planner.decisions[seen:]:
            log.write(json.dumps(d) + "\n")
            print(json.dumps(d))
        seen = len(planner.decisions)
        log.flush()
        if st["now_h"] >= spec.horizon_h - 1e-6 or (all(r["final_output_delivered"] and not r["assignments"]
                                                         for r in st["workloads"])):
            print(json.dumps({"end": "all delivered and cleaned up", "t": st["now_h"]}))
            break
        time.sleep(max(0.0, a.poll))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, requests.RequestException) as e:
        sys.exit(f"greenops.live failed: {e}")
