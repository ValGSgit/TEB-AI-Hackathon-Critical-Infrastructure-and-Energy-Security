# Challenge choice and pre-build (as of 21 Oct 2026)

## The five organizer challenges

| Challenge | Owner | Type of work | Judged on | Fit for our team of two |
| --- | --- | --- | --- | --- |
| Carbon-Aware Cloud Orchestration (GreenOps) | Exoscale | Code: scheduler for 15 workloads over 120 simulated hours, 11 zones | Objective score from an organizer rerun at 720x speed, plus pitch | **Best.** Pure engineering, measurable, pre-buildable |
| 5GDHC Quick Check Tool | ALG / Geothermie Österreich side | Code: web tool implementing a method handed out on Friday | Correct method, usability, clarity | Good. UI shell pre-buildable, method only on Friday |
| Business Models for 5GDHC | Anergie Leicht Gemacht | Business Model Canvas, reality check, pitch | Convincing, realistic business model | Weak. No code; needs heating-sector knowledge |
| Grid-Serving Storage | Smart Grids Austria | IES interoperability profile (processes and interfaces, no tech details) | Expert workshop result | Weak. Workshop with domain experts |
| Energy Communities 2.0 | Smart Grids Austria | IES interoperability profile for fair community energy management | Expert workshop result | Weak. Same as above |

None of the five covers pipeline security or location verification. ForceGeo fits only the open security tracks, and it is unclear whether those have their own jury or prize.

## Decision

Primary: **Exoscale GreenOps** (`greenops/`). Backup: ForceGeo (`forcegeo/`) for an open security track, if one is judged.

## Pre-built

- Residency guard (a forbidden-country placement disqualifies a run), checked twice before every create.
- Local simulator of the platform mechanics, with random practice scenarios shaped like the challenge.
- Baseline and carbon-aware policies; 19 tests pass.
- On 20 practice scenarios: same jobs delivered, carbon 15.9 kg (baseline) vs 4.3 kg (carbon-aware). Score formula is a stand-in.
- Exoscale API executor scaffold with TODOs for Friday.

## Ask the organizers before Friday

1. Is code written before the event allowed? (The GreenOps text allows general algorithm improvements between attempts and forbids only scenario-specific future knowledge.)
2. Can a team enter more than one challenge, and do the security tracks have a jury and prize?
3. When does GreenOps portal access open, and is the starter kit available before Friday?

## Friday plug-in list

1. Loader for the workload definitions, resource catalog and zones (`greenops/greenops/loaders.py`).
2. Fill the executor TODOs: user-data format, work-status API, instance-type names, template ID, run clock.
3. Replace the stand-in score with the frozen scoring policy; re-tune safety margin, buffer and minimum gain.
4. Practice run with the starter kit's two fixed workloads, then the full controller.
