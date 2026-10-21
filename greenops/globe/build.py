"""Build the GreenOps Earth page (one file) from a run JSON, the borders and the orbit data.

    python -m greenops.export --seed 3      # writes ui/data/run.json
    python globe/build.py                   # writes globe/earth.html (open in a browser; needs internet for three.js)
    python globe/build.py path/to/run.json
    python globe/build.py --bare            # body only, for hosts that add their own <html> shell

Orbit data and borders are shared with forcegeo/galileo-live/data. Refresh the TLEs before a demo.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "forcegeo", "galileo-live", "data")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
bare = "--bare" in sys.argv
src = args[0] if args else os.path.join(HERE, "..", "ui", "data", "run.json")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


nav = "" if bare else '<a href="../ui/dashboard.html" class="note">Control Room →</a>'
page = (read(os.path.join(HERE, "template.html"))
        .replace("/*__DATA__*/", read(src).replace("</", "<\\/"))
        .replace("/*__WORLD__*/", json.dumps(read(os.path.join(DATA, "world-50m.txt"))))
        .replace("__TLE_GAL__", read(os.path.join(DATA, "galileo.3le")).strip())
        .replace("__TLE_S2__", read(os.path.join(DATA, "s2.3le")).strip())
        .replace("__NAV__", nav))
if not bare:
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
out = os.path.join(HERE, "earth-bare.html" if bare else "earth.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print(f"wrote {out} ({os.path.getsize(out):,} bytes) from {src}")
