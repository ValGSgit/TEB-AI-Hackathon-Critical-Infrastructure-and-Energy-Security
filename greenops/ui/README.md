# GreenOps Control Room (UI)

One static page that explains a scheduling run: what ran when and where, why the planner waited,
how much carbon that saved against the baseline, and that no placement broke residency.

```bash
cd greenops
python -m greenops.export --seed 3      # simulate both policies, write ui/data/run.json
python ui/build.py                      # embed it -> ui/dashboard.html, open in a browser
```

The page can also load any run JSON with **Load run JSON**, so you can compare seeds without rebuilding.

## Views

| View | Answers | Pitch slot |
| --- | --- | --- |
| KPI row | Score, carbon vs the other policy, on-time delivery and bonus, residency, time spent waiting | Evidence |
| Allocation timeline | When each job waited, booted, set up, computed and delivered; zone; deadline | Approach |
| Carbon intensity by zone | Where the clean hours were and where we ran | Approach |
| Selected workload | Constraints, outcome, and a plain-language reason for when and where it ran | Trade-offs |
| Forecast vs what happened | How good the forecast was at each issue time | Limitations |
| Cumulative carbon, carbon per workload | Policy vs baseline, overall and per job | Evidence |
| Shared quota use | VMs, vCPUs, GPU cards against the limits | Trade-offs |
| Residency check | Allowed vs used countries per workload | Rules |
| Decision log | Every real change of plan with its carbon estimate and slack | Approach |

## Data contract (`schema: 1`)

Produced by `greenops/export.py`; checked by `tests/test_export.py`.

- `zones[]`: `id`, `country`, `pue`
- `workloads[]`: `id`, `kind`, `release_h`, `deadline_h`, `work_units`, `setup_h`, `output_h`, `allowed_countries[]`, `checkpoint_h`, `max_workers`
- `quotas`: `max_vms`, `max_vcpus`, `gpu_caps{family: cards}`
- `carbon_actual{zone: [g/kWh per hour]}`, `forecasts{zone: {issue_hour: [48 values]}}`
- `runs[]`: `policy`, `score{score, carbon_kg, delivered, of, all_done_bonus}`,
  `segments[]{vm, workload, zone, profile, phase, start, end}` (phases: booting, setup, running, delivering, done),
  `usage[]{t, vms, vcpus, gpus{family: n}}`, `carbon_series[]{t, carbon_kg}`,
  `workloads{id: {delivered, carbon_kg, first_start, delivered_at, waited_h, zones_used[]}}`,
  `decisions[]{t, workload, decision, zone, profile, workers, planned_start, carbon_now_g, carbon_best_g, slack_h}`

**Friday:** write a second exporter that fills the same fields from the real platform (allocation
timeline, work-status API, published forecasts). The page needs no changes. Fields the platform does
not give (for example `decisions`) come from our own controller's log.
