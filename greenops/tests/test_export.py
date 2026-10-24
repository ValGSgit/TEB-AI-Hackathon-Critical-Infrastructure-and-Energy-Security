"""The UI depends on this JSON shape; keep it stable (bump `schema` when it changes)."""
from greenops.export import build


def test_export_shape():
    d = build(1)
    assert d["schema"] == 1
    assert {r["policy"] for r in d["runs"]} == {"carbon-aware", "baseline"}
    zones = {z["id"]: z["country"] for z in d["zones"]}
    assert all(-90 <= z["lat"] <= 90 and -180 <= z["lon"] <= 180 for z in d["zones"])   # the globe needs these
    assert d["start_utc"].endswith("Z")
    assert set(d["carbon_actual"]) == set(zones)
    allowed = {w["id"]: set(w["allowed_countries"]) for w in d["workloads"]}
    for r in d["runs"]:
        assert set(r["workloads"]) == set(allowed)
        for s in r["segments"]:
            assert s["end"] > s["start"]
            assert zones[s["zone"]] in allowed[s["workload"]]      # the UI's residency view relies on this
        assert r["carbon_series"][-1]["carbon_kg"] >= r["carbon_series"][0]["carbon_kg"]
    for wid, ls in d["landscapes"].items():
        assert set(ls["zones"]) <= {z for z, c in zones.items() if c in allowed[wid]}   # only legal zones offered
        assert all(len(row) == len(ls["hours"]) for row in ls["grams"])
    ca = next(r for r in d["runs"] if r["policy"] == "carbon-aware")
    assert all(x["decision"] in ("wait", "start") for x in ca["decisions"])


def test_export_game_shape():
    """The real-challenge exporter feeds the same page: same schema, the planner's own decision log, legal zones."""
    from greenops.export_game import build as build_game
    d = build_game(1)
    assert d["schema"] == 1 and d["forecast_h"] == 24
    assert {r["policy"] for r in d["runs"]} == {"carbon-aware", "naive"}
    zones = {z["id"]: z["country"] for z in d["zones"]}
    assert len(zones) == 11 and all(-90 <= z["lat"] <= 90 and -180 <= z["lon"] <= 180 for z in d["zones"])
    assert all(len(v["0"]) == 24 for v in d["forecasts"].values())       # what the live API serves
    allowed = {w["id"]: set(w["allowed_countries"]) for w in d["workloads"]}
    for r in d["runs"]:
        assert set(r["workloads"]) == set(allowed)
        for s in r["segments"]:
            assert s["end"] > s["start"] and s["phase"] in {"booting", "setup", "running", "delivering", "done", "stopped", "waiting"}
            assert zones[s["zone"]] in allowed[s["workload"]]
    ca = next(r for r in d["runs"] if r["policy"] == "carbon-aware")
    assert {"create", "delete"} <= {x["action"] for x in ca["decisions"]}   # live decisions.jsonl format
    assert ca["score"]["delivered"] == 15
