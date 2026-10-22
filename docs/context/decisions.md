# Decisions (ADRs)

- **ADR-0001**: Primary challenge chosen: Exoscale Carbon-Aware Cloud Orchestration (`greenops/`). Best fit for our
  team of three (pure engineering, measurable outcome, pre-buildable). Backup: ForceGeo (`forcegeo/`) for the open
  security track.
- **ADR-0002**: Pre-build before the event using a local simulator and clearly marked stand-ins (scoring, durations,
  forecasts). Friday checklist: write `greenops/greenops/loaders.py`, fill executor TODOs, replace stand-in score, practice run.
- **ADR-0003**: Scheduling architecture: `Baseline` (fixed legal zone, start at release) vs `CarbonAware` (forecast-driven,
  replan every tick; options at release, wait for cleaner hours with safety margin, quota to tightest slack first, delete
  idle VMs). Experiment ladder runs one change at a time on shared seeds.
- **ADR-0004**: Residency guard is mandatory and checked twice (policy + executor) because a forbidden-country placement
  disqualifies the whole run even if the API rejects it.
- **ADR-0005**: UI and 3D globe consume a versioned JSON run export produced by `greenops.export` from the local
  simulator; a second exporter from the real platform is expected on Friday with no UI changes.
- **ADR-0006**: Agent instructions live in `AGENTS.md` (imported by `CLAUDE.md`) plus `docs/context/`. They are in
  English (file names and content), tool-neutral, put the disqualifying rules first, and are updated in the same
  commit as the change they describe. External skills are optional: nothing in the repo depends on them.
