# Prioritized UX Issues

## P0
1. Missing canonical next action path on Project Overview
- Impact: highest onboarding friction; users can stall before first successful run.
- Safe fix: persistent journey guide + stage-aware primary CTA.

2. Fragmented requirement-task-run narrative
- Impact: weak perceived lineage continuity and reduced runtime confidence.
- Safe fix: consistent lineage language and linked progression hints across views.

## P1
1. Inconsistent progressive disclosure
- Impact: new users see expert controls too early, slowing comprehension.
- Safe fix: default-emphasize setup controls, visually de-emphasize advanced actions.

2. Terminology drift across execution surfaces
- Impact: wayfinding confusion between Mission Control, Execution View, Run Viewer.
- Safe fix: standardize labels and helper copy.

3. Uneven recovery affordances in warning/failure states
- Impact: slower troubleshooting loops.
- Safe fix: “do this next” action near every warning state.

## P2
1. Cross-view setup state is not unified
- Impact: duplicate checking effort.
- Safe fix: shared readiness rail/checklist component.

2. Action density in single panels
- Impact: scanning cost for repeat users.
- Safe fix: grouped actions by phase (setup/planning/execution).

## Screenshot Evidence (Mission Control run table, 2026-05-09 capture)
1. Progressive disclosure leak is visible
- Evidence: search, run selection, build action, and dense status table are all equally prominent before a clear “recover this failed run” flow.
- Fix applied safely: keep failure recovery CTA primary; collapse secondary controls behind “More actions”.

2. Terminology drift is reinforced in this state
- Evidence: page header says `MISSION CONTROL`, while related surfaces are still referenced elsewhere as Execution View / Run Viewer.
- Fix applied safely: lock one canonical label in nav + helper copy (e.g., `Mission Control`) and use aliases only as subtitle text.

3. Recovery affordance is underpowered for failure/cancel mix
- Evidence: top card shows `FAILED`, rows show mostly `CANCELED`, but there is no dominant “Do this next” action adjacent to those states.
- Fix applied safely: add inline recovery actions per state (`Retry failed step`, `Resume from last successful step`, `Open failure diff/log`).

4. Cross-view setup state remains implicit
- Evidence: this screen shows execution outcomes but not upstream readiness (repo connected, requirements approved, tasks validated) in one place.
- Fix applied safely: add compact readiness rail at top of Mission Control with deep-links to setup surfaces.

5. Action density hurts scan speed in long-step rows
- Evidence: long natural-language step titles dominate row height; status and start-time become harder to compare quickly.
- Fix applied safely: two-line clamp for step text + hover expand + optional “compact rows” toggle.
