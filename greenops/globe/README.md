# GreenOps Earth

3D globe that replays a scheduling run over the real map and the real sky.

```bash
cd greenops
python -m greenops.export --seed 3      # simulate, write ui/data/run.json
python globe/build.py                   # -> globe/earth.html (needs internet for three.js and satellite.js)
```

## What it shows

| Element | Meaning |
| --- | --- |
| Zone dots | Data-centre zones at their cities, coloured by grid carbon intensity at the current hour (dim = clean, bright = dirty). Zones tagged **game** are fictional additions of the challenge |
| Teal bars | VMs our scheduler is running in that zone right now (height = count) |
| Teal arcs | Link from the controller (weXelerate, Vienna) to each zone in use; the moving dot is the control traffic |
| Pale blue points and rings | The 32 Galileo satellites and their three orbital planes, from real element sets |
| Pale blue lines | Galileo satellites at least 10° above a busy (or selected) zone: the satellites that zone can use for position and time |
| Violet markers and trails | Sentinel-2A, 2B and 2C (Copernicus imaging), with the last 14 minutes of track and the point below them |
| Lighting | Real sun position for that moment: day and night line up with the solar dips in the carbon data |

Simulated hour 0 is mapped to `start_utc` in the run file (default: Fri 23 Oct 2026 18:00 UTC, when hacking starts),
so the satellites are where they really will be during the run.

Controls: play/pause (space), speed, scrubber (the shaded strip is VMs running), policy toggle, layers, camera presets,
click a zone (list or label) to fly there and show its satellite links.

## Data

Reads the same run JSON as the Control Room (`../ui/README.md`), plus `lat`, `lon`, `city`, `real_zone` per zone and
`start_utc`. Borders and orbit data come from `forcegeo/galileo-live/data/` (refresh the `.3le` files before the demo).
