"""Build galileo-live.html from template.html and the data folder.

    python build.py                          # vector borders only
    python build.py world.jpg region.jpg     # embed Sentinel-2 cloudless imagery (EOX, CC BY-NC-SA 4.0)

Refresh data/galileo.3le and data/s2.3le (CelesTrak element sets) the evening before a demo.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def img(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


t = (read(HERE, "template.html")
     .replace("__WORLD__", read(DATA, "world-50m.txt"))
     .replace("__S2TLE__", read(DATA, "s2.3le").strip())
     .replace("__TLE__", read(DATA, "galileo.3le").strip())
     .replace("__S2WORLD__", img(sys.argv[1] if len(sys.argv) > 1 else ""))
     .replace("__S2REGION__", img(sys.argv[2] if len(sys.argv) > 2 else "")))
out = os.path.join(HERE, "galileo-live.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(t)
print(f"wrote {out} ({len(t):,} bytes)")
