# Vessel Known Issues — Phase 18

## Batch Render

Batch folder:

`outputs/vessels/batch_2026-04-28_23-54-11`

Rendered examples:

1. V201
2. V202_SMALL
3. V203_LONG
4. V204_END_NOZZLES
5. V205_CLUSTERED

All five DXF files rendered successfully and opened in AutoCAD.

---

## Issue 1 — Scale Selection Too Conservative

### Affected examples

- V201
- V204_END_NOZZLES
- V205_CLUSTERED

### Problem

The renderer selects `1:50` for several vessels where the views appear too small on the A1 sheet. This creates excessive empty space and makes the drawing less readable.

### Current behavior

V201 selected:

`Scale: 1:50`

Expected preferred scale for V201 should be closer to:

`1:20`

### Severity

Medium

### Proposed fix

Improve `choose_sheet_layout()` and the view bounding box estimates in `sheet.py`.

The current extents are too conservative because they include large padding for dimensions and callouts.

---

## Issue 2 — Dimension Crowding on Small Vessel

### Affected examples

- V202_SMALL

### Problem

For small vessels, dimensions and callouts occupy too much space relative to the vessel body. The drawing is readable but visually crowded.

### Severity

Medium

### Proposed fix

Add dynamic dimension offsets based on vessel diameter and tangent length.

Small vessels should use smaller dimension offsets and smaller callout spacing.

---

## Issue 3 — Nozzle Dimension and Callout Crowding

### Affected examples

- V203_LONG
- V205_CLUSTERED

### Problem

Multiple top/bottom nozzles create crowded location dimensions and overlapping callout areas.

The clustered nozzle case intentionally exposes this problem.

### Severity

High for clustered nozzles

### Proposed fix

Improve nozzle callout placement logic:

- stagger labels more intelligently
- group close nozzles
- increase vertical offset only when needed
- avoid placing callouts directly on top of dimension text

---

## Issue 4 — Clustered Nozzles Need Special Handling

### Affected example

- V205_CLUSTERED

### Problem

Nozzles placed close together cause dimension and callout collisions.

### Severity

High

### Proposed fix

Detect nozzles whose axial positions are close together and apply a clustered-nozzle dimensioning strategy.

Possible strategy:

- use stacked callouts
- use one shared baseline dimension
- use staggered leader lines
- move callouts outside the vessel envelope

---

## Issue 5 — End-Nozzle Vessel Uses Too Much Sheet Space

### Affected example

- V204_END_NOZZLES

### Problem

The vessel renders correctly, but the selected scale makes the views too small.

### Severity

Low to medium

### Proposed fix

Same as Issue 1: improve sheet scale selection.

---

## Phase 18 Fix Priority

1. Fix scale selection for V201, V204, V205.
2. Improve nozzle callout spacing.
3. Improve clustered-nozzle dimension handling.
4. Improve small-vessel dimension spacing.
5. Re-run batch render and compare screenshots.

---

## Current Phase 18 Status

Batch render succeeded.

Visual review completed.

Known issues documented.

Phase 18 is not complete yet because the visual issues still need to be fixed and the batch render must be re-run.

## Issue — Sheet Layout Spacing Still Needs Manual Cleanup

### Affected examples

- V201
- V202_SMALL
- V203_LONG
- V204_END_NOZZLES
- V205_CLUSTERED

### Problem

The Phase 18 batch renderer successfully generates all five vessel drawings, but the sheet layout still needs visual tuning.

Two problems were observed during AutoCAD review:

1. When scale is forced or selected too tightly, the drawing becomes congested.
2. When the layout is relaxed, the gap between the views and the bottom BOM/title block becomes too large.

The main conflict is between:
- keeping the vessel views readable,
- preventing dimensions from overlapping the BOM,
- avoiding too much unused blank space,
- and choosing the correct sheet scale automatically.

### Current status

All drawings render successfully and open in AutoCAD.

This is not a blocker for continuing the pipeline, but it is not fully production-clean yet.

### Severity

Medium

### Decision

Deferred for later cleanup.

### Future fix

Refine `sheet.py` layout logic and `render.py` label placement together.

Possible fixes:

- keep V201 and simple vessels at `1:20`
- keep long or clustered vessels at `1:50`
- dynamically calculate the bottom-most dimension point
- place the BOM/title block after checking drawing extents
- prevent `FRONT VIEW` label from overlapping the BOM
- reduce excess vertical spacing without causing dimension collisions