"""Embed a run JSON into the UI so it opens as one file.

    python -m greenops.export --seed 3          # writes ui/data/run.json
    python ui/build.py                          # writes ui/dashboard.html (open it in a browser)
    python ui/build.py path/to/other-run.json   # embed a different run
    python ui/build.py --bare                   # page body only, for hosts that add their own <html> shell
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
bare = "--bare" in sys.argv
src = args[0] if args else os.path.join(HERE, "data", "run.json")
with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
    page = f.read()
with open(src, encoding="utf-8") as f:
    data = f.read().replace("</", "<\\/")      # keep the JSON from closing the script tag
page = page.replace("/*__DATA__*/", data)
if not bare:
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
out = os.path.join(HERE, "dashboard-bare.html" if bare else "dashboard.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print(f"wrote {out} ({os.path.getsize(out):,} bytes) from {src}")
