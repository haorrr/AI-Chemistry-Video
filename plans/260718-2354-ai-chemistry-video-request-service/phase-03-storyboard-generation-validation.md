---
phase: 3
title: "Storyboard Generation & Validation"
status: completed
priority: P1
effort: "2-3h"
dependencies: [2]
---

# Phase 3: Storyboard Generation & Validation

## Overview
Deterministic storyboard templates (the AI/LLM generation boundary) for the 3 required concepts,
validated with Pydantic, saved to `artifacts/{job_id}/storyboard.json`. Maps to master prompt
§10, §11, §18 Step 4.

## Requirements
- Functional: `generate_storyboard(concept: str) -> Storyboard` returns a valid, deterministic
  storyboard for each of `ph_scale`, `covalent_bonds`, `ionic_vs_covalent`.
- Functional: storyboard schema validation per master prompt §11 (3-6 scenes, required fields,
  visual_type restricted to the 5 literal values).
- Functional: if the primary template's construction/validation raises, fall back to a genuinely
  different, minimal, always-valid template rather than retrying the identical primary template
  (PLAN_REVIEW #10 — a broken primary template would otherwise fail identically on "retry").
- Functional: each concept's narration content is scientifically accurate per the corrections in
  Implementation Step 2 below (PLAN_REVIEW #13).
- Non-functional: generator function signature/module isolated so a real LLM call could replace
  the body later without changing callers (master prompt §5, §12 "Provider Boundary").

## Architecture
`storyboard_generator.py` exposes one public function `generate_storyboard(concept: str) ->
Storyboard` that internally dispatches to per-concept template builders, wrapped in a
try/except that falls back to `_safe_fallback_storyboard(concept)` on any exception. This is the
single swap point mentioned in ARCHITECTURE.md for plugging in a real LLM later — do not leak
template logic into other modules.

## Related Code Files
- Modify: `app/models.py` — add `Scene(BaseModel)` and `Storyboard(BaseModel)` per master
  prompt §11 schema, with field validators (title non-empty, concept in supported set, 3-6
  scenes, visual_type as `Literal[...]`).
- Create: `app/services/storyboard_generator.py`
- Use (not create): `app/services/artifact_store.py` (from Phase 1) for `storyboard_path(job_id)`
  and atomic JSON write.

## Implementation Steps
1. `models.py`: add `Scene` (heading, visual_type: Literal["title","ph_scale","atom_sharing",
   "comparison_table","summary"], visual_text, narration) and `Storyboard` (title, concept,
   scenes: list[Scene], min_length=3, max_length=6) with a validator enforcing `concept` is one
   of the 3 supported concept keys.
2. `storyboard_generator.py`: write 3 deterministic primary templates (4-5 scenes each per master
   prompt §13), one function per concept (`_ph_scale_storyboard()`, `_covalent_bonds_storyboard()`,
   `_ionic_vs_covalent_storyboard()`), content drawn from master prompt §10.1-10.3 with these
   accuracy corrections (PLAN_REVIEW #13):
   - **pH scale**: explicitly state the scale is **logarithmic** — each 1-unit drop in pH means
     roughly a 10x increase in H⁺ concentration. Don't just say "more H⁺ = more acidic" without
     the logarithmic qualifier.
   - **Covalent bonds**: avoid absolute claims like "atoms always reach a full outer shell" —
     use "sharing electrons generally helps atoms reach a more stable electron configuration"
     (some covalent compounds are stable without a full octet, e.g. odd-electron species).
   - **Ionic vs covalent**: the `comparison_table` scene alone isn't enough — add a scene (or
     extend an existing one) whose `visual_text`/narration explicitly describes an **electron
     transfer arrow** (Na → Cl⁻, one electron moving) distinct from the shared-pair diagram, so
     the visual contrast between "transfer" and "share" is unambiguous (ties into Phase 5's
     renderer needing a distinct visual element for this, not just table text).
   - Add a lightweight semantic check (can be a plain assertion in a unit test, not runtime
     validation): each storyboard's combined narration text contains specific required keywords
     per concept (e.g. `ph_scale` → "logarithmic"; `ionic_vs_covalent` → "transfer" and "share").
     Catches silent content regressions if templates are edited later.
3. `storyboard_generator.py`: `_safe_fallback_storyboard(concept: str) -> Storyboard` — one
   generic, minimal 3-scene template (title/summary/summary visual types only — types guaranteed
   safe to render even if a concept-specific diagram type had a rendering bug) used **only** when
   the primary template construction/validation raises. This is deliberately a *different*
   template from primary, not a retry of the same one (PLAN_REVIEW #10) — if the primary
   template for a concept is broken, retrying it would fail identically.
4. `generate_storyboard(concept)`:
   ```python
   try:
       return _PRIMARY_TEMPLATES[concept]()
   except Exception as e:
       logger.error(f"Primary storyboard template failed for {concept}: {e}")
       try:
           return _safe_fallback_storyboard(concept)
       except Exception:
           raise StoryboardGenerationError(
               f"Both primary and fallback storyboard generation failed for {concept}"
           )
   ```
   Raise a clear internal exception if `concept` isn't in `_PRIMARY_TEMPLATES` (should never
   happen post-registry-validation).
5. Add `save_storyboard(job_id, storyboard) -> Path` writing `artifacts/{job_id}/storyboard.json`
   via `artifact_store.storyboard_path(job_id)` + `artifact_store.atomic_write_json(...)`.

## Success Criteria
- [x] `generate_storyboard("ph_scale")` etc. return a `Storyboard` that passes Pydantic validation for all 3 concepts.
- [x] Each storyboard has 4-5 scenes, matches content in master prompt §10 plus the accuracy
      corrections above.
- [x] Unsupported `visual_type` values are rejected by the schema (verified with a quick unit test).
- [x] `storyboard.json` written to the correct artifact path with valid JSON, via atomic write.
- [x] Unit test: monkeypatch a primary template to raise → `generate_storyboard()` returns the
      safe fallback storyboard instead of propagating the exception (proves fallback is a real,
      independently-testable path, not just theoretical).
- [x] Unit test: monkeypatch **both** primary and fallback to raise → `generate_storyboard()`
      raises `StoryboardGenerationError`.
- [x] Each primary storyboard's narration contains the concept-specific required keywords
      (logarithmic / transfer+share).

## Review Log (2026-07-19)
Reviewed by code-reviewer subagent. Score: 9/10. All 37 tests pass (23 prior + 14 new), verified
by running pytest directly. `app.main` imports cleanly. All 3 PLAN_REVIEW #13 content-accuracy
fixes confirmed present by reading narration text directly (logarithmic pH relationship, softened
covalent octet claim, distinct ionic electron-transfer scene). No regressions against Phase 4/5/6
interface assumptions (grepped all 4 phase files for every Phase 3 symbol). No critical/high
issues. Two non-blocking medium findings documented in the full report:
1. `models.SUPPORTED_CONCEPTS` duplicates `topic_registry.SUPPORTED_QUERIES` values instead of
   deriving from it — fine at current fixed 3-concept scope, flag if a 4th concept is ever added.
2. `_safe_fallback_storyboard` protects against primary-template logic bugs but not against a bug
   in the shared `Scene`/`Storyboard` Pydantic models themselves (both paths construct the same
   classes) — accepted as out of this phase's intended scope (PLAN_REVIEW #10 targeted template
   bugs, not schema bugs), and already covered by the phase's own Storyboard/Scene validation unit
   tests.

No stop-and-ask-user gate triggered — no regressions, no contract breaks, no content-accuracy
failures. Full report: `plans/reports/code-reviewer-260719-0059-phase3-storyboard-review-report.md`.

**Next step**: commit Phase 3 changes (`app/models.py`, `app/services/storyboard_generator.py`,
`tests/test_phase3.py`), then proceed to Phase 4 (Audio Narration Service).

## Risk Assessment
Primary templates are hand-written and deterministic, so they should always validate in
practice — but PLAN_REVIEW correctly points out that "fallback = same template" gives zero
actual protection against a template bug, which contradicts the reliability intent in master
prompt §11-12. The `_safe_fallback_storyboard` addition is small (one generic template, ~15
lines) and directly closes that gap without building unnecessary LLM-style retry/regeneration
machinery, which genuinely isn't needed for static templates.
