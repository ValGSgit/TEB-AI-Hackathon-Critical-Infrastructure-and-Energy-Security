"""Executor for the real GreenOps platform (Exoscale-compatible API).

SCAFFOLD. What we know from the challenge text:
  * VMs are created through an Exoscale-compatible API subset (python binding: `exoscale`).
  * A VM gets its workload by putting the workload ID in the VM's user-data.
  * Progress comes from a separate work-status API.
  * Each run has its own credentials and endpoints (one per zone).
What we only learn on Friday (marked TODO): the user-data format, the work-status URL and
response shape, template IDs, and how run time/forecasts are exposed. Fill those in and
keep everything else.
"""
from __future__ import annotations

import base64
import os

import requests
from exoscale.api.v2 import Client

from .guard import check_placement
from .model import RunState, VMState, WorkloadState


class ExoscaleExecutor:
    def __init__(self, ctx, zone_endpoints: dict, status_url: str, template_id: str,
                 key: str | None = None, secret: str | None = None, label="greenops"):
        self.ctx = ctx
        key = key or os.environ["EXOSCALE_API_KEY"]          # never hard-code credentials
        secret = secret or os.environ["EXOSCALE_API_SECRET"]
        self.clients = {z: Client(key, secret, url=url) for z, url in zone_endpoints.items()}
        self.status_url, self.template_id, self.label = status_url, template_id, label
        self.vm_zone = {}          # vm id -> zone id
        self._type_ids = {}        # (zone, profile name) -> instance-type id

    # ---------- helpers ----------
    def _instance_type_id(self, zone_id, profile_id):
        key = (zone_id, profile_id)
        if key not in self._type_ids:
            fam, size = profile_id.split(".", 1)              # e.g. "standard.large" -- TODO confirm naming
            for t in self.clients[zone_id].list_instance_types()["instance-types"]:
                if t.get("family") == fam and t.get("size") == size:
                    self._type_ids[key] = t["id"]
                    break
            else:
                raise KeyError(f"no instance type {profile_id} in {zone_id}")
        return self._type_ids[key]

    @staticmethod
    def _user_data(workload_id: str) -> str:
        # TODO: replace with the exact format from the starter kit
        return base64.b64encode(f"workload_id: {workload_id}\n".encode()).decode()

    # ---------- executor interface ----------
    def create_vm(self, workload_id, zone_id, profile_id):
        check_placement(self.ctx.W[workload_id], self.ctx.Z[zone_id])   # last line of defence
        c = self.clients[zone_id]
        op = c.create_instance(
            name=f"{self.label}-{workload_id}-{len(self.vm_zone)}",
            instance_type={"id": self._instance_type_id(zone_id, profile_id)},
            template={"id": self.template_id},
            disk_size=10,
            user_data=self._user_data(workload_id),
            labels={"workload": workload_id, "app": self.label},
        )
        vm_id = op["reference"]["id"]
        self.vm_zone[vm_id] = zone_id
        return vm_id

    def delete_vm(self, vm_id):
        self.clients[self.vm_zone.pop(vm_id)].delete_instance(id=vm_id)

    def observe(self) -> RunState:
        # TODO: map the real work-status response; the shape below is a guess
        s = requests.get(self.status_url, timeout=10).json()
        vms = [VMState(v["id"], v["workload_id"], v["zone"], v["profile"], v["phase"], v.get("created_h", 0))
               for v in s.get("vms", [])]
        ws = {w["id"]: WorkloadState(w["id"], w.get("progress", 0), w.get("checkpointed", 0),
                                     w.get("delivered", False), w.get("failed", False))
              for w in s.get("workloads", [])}
        return RunState(s.get("now_h", 0.0), s.get("horizon_h", 120.0), vms, ws)

    def finished(self) -> bool:
        st = self.observe()
        return st.now_h >= st.horizon_h
