# Glossary

- **Carbon-aware orchestration**: choosing where and when each workload runs so the same electricity comes from a
  cleaner grid (carbon = energy × grid intensity), within deadlines, residency and quotas.
- **gCO2/kWh**: grams of CO2 equivalent per kilowatt-hour of grid energy.
- **PUE**: facility-efficiency factor; includes overhead of the data centre (simulated values like 1.15–1.25).
- **Forecast**: predicted carbon intensity per electricity area (country) per hour, 6 or 24 h ahead, published by the
  run; the planner may only use values issued up to now.
- **DQ / disqualification**: the run is disqualified for a residency violation; scoring returns zero.
- **Residency**: workload allowed countries; placement outside them is forbidden.
- **Checkpoint**: saved progress before a restart; restart-sensitive jobs lose progress.
- **Work units**: unit of compute work a workload needs.
- **Slack**: hours available between planned start plus duration and the deadline.
- **Horizon**: simulated window of a run (120 h in the challenge).
- **Quota**: max VMs (20), max vCPUs (320), GPU card caps per family.
- **Phase**: platform allocation timeline phase (Booting, Input/setup, Computing, Stopped, Idle, Output waiting, Waiting for release).
- **Baseline policy**: fixed legal zone, start at release, lowest-energy option meeting the deadline.
- **CarbonAware policy**: replans every tick over legal options and cleaner forecast windows; safety margin 1.2x, buffer 2h, min gain 3%.
- **Experiment ladder**: baseline -> +cleanest zone -> +wait for cleaner hours -> idle-VM ablation, on the same seeds.
- **Block**: the hours `[start, end)` a job holds quota in the real-challenge plan, running or stopped.
- **Soft end**: `slack_h` hours before a job's latest end; the planner aims to finish by then when it fits.
- **Kept start (commit)**: a start planned within `commit_h` hours, held at the next re-plans instead of re-optimized.
- **Urgent job**: a job that once found no slot; planned right after created jobs until it is created (ADR-0013).
- **Run hours**: the hours inside a block in which the job runs (the cleanest ones); in the others its VMs are stopped.
- **Stop / resume**: a stopped VM draws no electricity and keeps all work and staged input, but still holds its quota
  and worker slot; resuming does not repeat boot or input.
- **Bootstrap**: the first create, made while the run is READY; it starts the run clock.
- **Adopt**: after a controller restart, take over VMs that already exist instead of creating new ones.
- **Probe**: `greenops.live --probe`, a read-only check of a run's APIs and of the plan, creating nothing.
- **Reference energy**: fixed kWh per workload in `rules.json` that weights the score (v2: 20,000 base, +5,000 if all
  on time, quality vs 200 gCO2e/kWh, 3/4 per-workload and 1/4 run-wide cost).
- **Stand-in score**: local scoring formula (20k base + 5k bonus) until the organizers' frozen policy is plugged in.
- **Galileo / Sentinel-2**: satellites used for position/time (Galileo) and imaging (Sentinel-2) in the ForceGeo demos
  and as optional context layers in the GreenOps Earth view; the GreenOps challenge itself uses no satellite data.
- **Spoofing**: replaying a sky/track to make a receiver believe a satellite position that was not really observed.
