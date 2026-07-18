# Phase 3 (Storyboard Generation & Validation) Code Review

Plan: `plans/260718-2354-ai-chemistry-video-request-service/plan.md` + `phase-03-storyboard-generation-validation.md`

## Scope
- Files reviewed: `app/models.py` (diff), `app/services/storyboard_generator.py` (new), `tests/test_phase3.py` (new)
- Cross-checked: `app/services/artifact_store.py`, `app/services/topic_registry.py`, `app/utils/logging.py`, phase-04/05/06 plan files
- ~260 LOC reviewed (models diff ~25 lines, generator 219 lines, tests 193 lines)
- Focus: uncommitted Phase 3 diff only

## Score: 9/10

## Overall Assessment
Solid, matches phase spec closely. All 37 tests pass (23 prior + 14 new), verified by running pytest myself, not trusting prior tester report. `app.main` imports cleanly. Content-accuracy fixes from PLAN_REVIEW #13 are actually present in the narration text, not just keyword-stuffed. No regressions found against Phase 4/5/6 interface assumptions. One pre-existing DRY gap (not introduced by this phase, but this phase adds to it) and one inherent design-limitation worth documenting.

## Critical Issues
None.

## High Priority Findings
None.

## Medium Priority Improvements

1. **`SUPPORTED_CONCEPTS` in `models.py` duplicates `topic_registry.SUPPORTED_QUERIES` values instead of deriving from it.** `topic_registry.py`'s own docstring says it's "Single source of truth for... topic scope / single place to add topics later" (also stated in plan.md's Architecture Summary: "Topic registry: owns supported-concept scope; single place to add topics later"). `models.py` now hardcodes the same 3 concept keys a second time (`SUPPORTED_CONCEPTS = {"ph_scale", "covalent_bonds", "ionic_vs_covalent"}`). Today they're consistent; if a concept is ever added to `topic_registry.SUPPORTED_QUERIES` without updating `models.SUPPORTED_CONCEPTS`, `Storyboard` validation will reject a query the registry accepts — silent contract mismatch. Not blocking for this locked-scope prototype (3 concepts, no more, per plan Non-Goals), but flag for anyone touching this later. Cheap fix: derive `SUPPORTED_CONCEPTS` from `topic_registry.SUPPORTED_QUERIES.values()` (would need to watch for import-cycle direction — `models.py` currently has no deps, `topic_registry.py` currently has none either, so either direction works).

2. **Residual risk (explicitly asked about): `_safe_fallback_storyboard` does not protect against a bug in the shared `Scene`/`Storyboard` Pydantic models themselves**, only against a bug in a specific primary template function's logic. Verified by reading the code: both `_ph_scale_storyboard()` (and siblings) and `_safe_fallback_storyboard()` construct instances of the *same* `Storyboard`/`Scene` classes from `app.models`. If a defect were introduced into `Scene`/`Storyboard` itself (e.g. a validator that now rejects valid `visual_text`, or a new required field none of the templates supply), primary and fallback would raise identically, and `generate_storyboard()` would surface `StoryboardGenerationError` for every concept — the exact "fails identically" failure mode PLAN_REVIEW #10 was written to eliminate, just one layer up.
   - **Verdict: acceptable residual risk for this prototype, worth documenting rather than fixing.** Reasoning: (a) `_safe_fallback_storyboard` was scoped by the phase spec as protection against a broken *template* (business-logic bug), not a broken *schema* — a schema-level bug is a different, much rarer failure class that would also break Phase 2's job creation flow and would be caught immediately by the 7 dedicated `Storyboard`/`Scene` validation unit tests already in `test_phase3.py` before it ever reached templates. (b) Building true independence (e.g. a fallback that bypasses Pydantic validation entirely) would add real complexity for a defense against a bug class the plan's own Risk Assessment doesn't ask for. Recommend adding one sentence to `phase-03`'s Risk Assessment section noting this scope boundary explicitly, so a future reader doesn't assume the fallback covers model-level bugs — but no code change needed.

## Low Priority Suggestions
- None beyond the above — code is clean, typed, and follows existing patterns (atomic write via `artifact_store.atomic_write_json`, `get_logger(__name__)` matching Phase 1/2 style, `Path` return types, no dead code, no stray prints).

## Positive Observations
- **Content accuracy verified by direct read, not trust**: all three PLAN_REVIEW #13 corrections are concretely present:
  - pH scale scene 2 narration: *"The pH scale is logarithmic: each one-unit drop in pH means roughly a tenfold increase in hydrogen ion concentration. A solution with pH 4 has about ten times more H+ ions than one with pH 5."* — states logarithmic + the ~10x-per-unit relationship, not just "more H+ = more acidic."
  - Covalent bonds scene 2 narration: *"Sharing electrons generally helps atoms reach a more stable electron configuration."* — uses "generally"/"more stable," no "always reach a full octet" absolute claim anywhere in the file (grepped).
  - Ionic vs covalent has a **dedicated** "Electron Transfer (Ionic)" scene (`visual_text="Na -- electron transfer arrow --> Cl, forming Na+ and Cl-"`) that is structurally distinct from both the "Electron Sharing (Covalent)" scene and the later "Transfer vs Share" `comparison_table` scene — satisfies Phase 5's stated need for a renderable, explicit electron-transfer-arrow element separate from the shared-pair diagram and separate from table text.
- **Fallback design is real, not theoretical**: `_safe_fallback_storyboard` uses a genuinely different template (3 generic scenes, `title`/`summary` visual types only) rather than retrying the same primary function — correctly closes PLAN_REVIEW #10's gap at the template-logic layer. Verified independently testable via the monkeypatch tests, which I confirmed pass.
- **No Phase 4-6 contract breaks found.** Grepped phase-04 through phase-07 for every symbol named in the task (`generate_storyboard`, `save_storyboard`, `Storyboard`, `Scene`, `storyboard_generator`, `StoryboardGenerationError`): phase-06 pseudocode calls `storyboard_generator.generate_storyboard(job.concept)` / `.save_storyboard(job_id, storyboard)` exactly as implemented; phase-05 references `Scene` for `_draw_slide(scene: Scene, ...)` and needs `scene.visual_type`/`visual_text`/`heading` — all present on the actual `Scene` model. Phase 4's `generate_narration(job_id, storyboard)` needs to iterate `storyboard.scenes` and read `scene.narration` per scene — both fields exist with correct types (`str`).
- Test suite genuinely exercises both failure paths (primary-only failure → fallback; primary+fallback failure → `StoryboardGenerationError`) via `monkeypatch.setitem`/`setattr` on the actual module dict/function, not mocks of unrelated surfaces.
- `save_storyboard` reuses `artifact_store.storyboard_path` + `atomic_write_json` exactly as Phase 1 intended — no ad-hoc path building, matches the architecture boundary rule in plan.md.

## Recommended Actions
1. (Optional, non-blocking) Add one sentence to phase-03's Risk Assessment documenting that the fallback protects against template-logic bugs, not shared-model schema bugs.
2. (Optional, non-blocking, can defer to whenever a 4th concept is ever added) Derive `models.SUPPORTED_CONCEPTS` from `topic_registry.SUPPORTED_QUERIES.values()` instead of duplicating the literal set.
3. Proceed to commit Phase 3 and move to Phase 4 — no blocking issues.

## Metrics
- Test Coverage: 37/37 passing (23 prior + 14 new), verified via `./.venv/Scripts/python.exe -m pytest tests/ -v`
- Type Coverage: full type hints on all new public functions/models; no `Any` usage
- Lint/Type errors: no lint/type tooling configured in repo (no ruff/mypy/flake8/pyproject.toml found) — verified via `py_compile` (clean) and `ast.parse` (clean) instead; `import app.main` succeeds with no errors
- Import errors: none

## Side Effects Requiring Stop-and-Ask-User Gate
**None.** No regressions, no contract breaks against Phase 4-7 assumptions, no content-accuracy failures. Safe to proceed without user intervention.

## Unresolved Questions
None — all items in the task brief were independently verified (tests run directly, narration text read directly, phase 4-7 grepped directly, model bug residual-risk question analyzed directly).
