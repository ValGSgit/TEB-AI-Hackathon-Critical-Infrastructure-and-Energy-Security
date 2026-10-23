"""A fake GreenOps platform for tests: the API subset greenops.live uses, served over the offline Game.

Every work-status call advances simulated time by `step_h`, so a whole run takes a few seconds.
No signatures are checked; the point is the request shapes, the URLs and the control loop.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from greenops.game import Game, make_grid
from greenops.spec import load, to_ts


class Fake:
    def __init__(self, seed=1, step_h=0.25):
        self.spec = load()
        self.grid = make_grid(seed, {s.area for s in self.spec.sites.values()})
        self.game = Game(self.spec, self.grid)
        self.step_h, self.started, self.calls = step_h, False, []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.cloud = self.base + "/runs/r1/cloud/v2"
        self.grid_url = self.base + "/runs/r1/grid/v4"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def advance(self):
        if self.started:
            end = min(self.game.now + self.step_h, self.spec.horizon_h)
            while self.game.now < end - 1e-9:
                self.game.step()

    def status(self):
        st = self.game.status()
        state = "READY" if not self.started else ("COMPLETED" if self.game.now >= self.spec.horizon_h - 1e-9 else st["state"])
        return {"run_id": "r1", "virtual_time": to_ts(self.game.now), "speed_multiplier": 720, "state": state,
                "qualification": st["qualification"],
                "workloads": [{"id": w["id"], "state": "x", "required_work": str(w["required_work"]),
                               "completed_work": str(w["completed_work"]), "work_unit": "vcpu_hour",
                               "lost_work": str(w["lost_work"]), "output_ready_at": None,
                               "succeeded_at": None, "final_output_delivered": w["final_output_delivered"],
                               "assignments": w["assignments"]} for w in st["workloads"]]}

    def _handler(fake):
        P = {p.id: p for p in fake.spec.profiles}

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"       # keep-alive, like the real API

            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method):
                path, _, query = self.path.partition("?")
                fake.calls.append((method, path))
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                g = fake.game
                if path == "/runs/r1/cloud/v2/zone":
                    return self._send(200, {"zones": [{"name": z.id, "api-endpoint": f"{fake.base}/runs/r1/cloud/{z.id}/v2"} for z in fake.spec.zones]})
                if path == "/runs/r1/work/v1/status":
                    fake.advance()
                    return self._send(200, fake.status())
                if path.startswith("/runs/r1/grid/v4/carbon-intensity/forecast"):
                    q = dict(kv.split("=") for kv in query.split("&"))
                    assert q["horizonHours"] in ("6", "24")
                    vals = fake.grid.forecast(q["zone"], g.now, int(q["horizonHours"]))
                    return self._send(200, {"zone": q["zone"], "forecast": [{"datetime": to_ts(int(g.now) + k), "carbonIntensity": v}
                                                                            for k, v in enumerate(vals)], "updatedAt": to_ts(int(g.now))})
                m = re.fullmatch(r"/runs/r1/cloud/([a-z0-9-]+)/v2/(.*)", path)
                if not m:
                    return self._send(404, {"message": "no route"})
                zone, rest = m.groups()
                if rest == "instance-type":
                    return self._send(200, {"instance-types": [{"id": p.id, "family": fake.spec.pinfo[p.id].family,
                                                                "size": fake.spec.pinfo[p.id].size} for p in P.values() if p.available_in(zone)]})
                if rest == "template":
                    return self._send(200, {"templates": [{"id": "tpl-1", "name": "Linux"}]})
                if rest == "instance" and method == "GET":
                    return self._send(200, {"instances": [{"id": v.id, "name": getattr(v, "name", v.id), "instance-type": {"id": v.profile_id}} for v in g.vms.values() if v.zone_id == zone]})
                if rest == "instance" and method == "POST":
                    import base64
                    wid = json.loads(base64.b64decode(body["user-data"]))["greenops"]["workload_id"]
                    try:
                        vid = g.create(wid, zone, body["instance-type"]["id"])
                    except ValueError as e:
                        return self._send(400, {"message": str(e)})
                    except Exception as e:
                        return self._send(403, {"message": str(e)})
                    g.vms[vid].name = body["name"]
                    fake.started = True
                    return self._send(200, {"id": "op-" + vid, "state": "pending", "reference": {"id": vid}})
                m2 = re.fullmatch(r"instance/([a-z0-9-]+)(:stop|:start)?", rest)
                if m2:
                    vid, verb = m2.groups()
                    if method == "DELETE":
                        g.delete(vid)
                    elif verb == ":stop":
                        g.stop(vid)
                    elif verb == ":start":
                        g.start(vid)
                    return self._send(200, {"id": "op", "state": "success", "reference": {"id": vid}})
                return self._send(404, {"message": "no route"})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PUT(self):
                self._route("PUT")

            def do_DELETE(self):
                self._route("DELETE")
        return H
