"""Control loop: observe -> decide -> act, until the window closes."""
from __future__ import annotations

from .policy import Context, apply
from .scenario import Scenario
from .sim import Sim


def run_sim(sc: Scenario, policy, dt: float = 0.25, verbose: bool = False) -> dict:
    sim = Sim(sc, dt=dt)
    ctx = Context(sc.zones, sc.profiles, sc.workloads, sc.quotas, sc.boot_h,
                  forecast=sc.carbon.forecast, dt=dt)
    while sim.now < sc.horizon_h - 1e-9:
        state = sim.observe()
        apply(sim, ctx, policy.decide(ctx, state))
        sim.step()
        if sim.disqualified:
            break
    res = sim.score()
    res["policy"] = policy.name
    if verbose:
        for row in sim.log:
            print(row)
    return res


def run_live(executor, ctx: Context, policy, poll_s: float = 2.0) -> None:
    """Same loop against the real platform. `executor` provides observe/create_vm/delete_vm/finished."""
    import time
    while not executor.finished():
        state = executor.observe()
        apply(executor, ctx, policy.decide(ctx, state))
        time.sleep(poll_s)
