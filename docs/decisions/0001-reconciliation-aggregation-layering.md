# ADR 0001 — Reconciliation aggregation layering (Layer 3 multi-delivery + ordering)

- **Status:** Accepted
- **Date:** 2026-06-23
- **Area:** `backend/app/reconciliation/`
- **Pilot data referenced:** 江西丰裕达电子科技有限公司 (vendor_code `XFY201`), period `2026-03`

## Context

The supplier reconciliation engine runs a waterfall of matching layers. The ERP
(SGWERP) logs **one row per physical delivery**, so a single
`(po_number, material_number)` can produce several ERP rows in one month — one per
delivery day. The supplier statement, by contrast, frequently **combines** those
deliveries into one line, or **splits** them differently from the ERP.

Two defects motivated this change:

1. **Layer 3 did not aggregate multi-delivery rows.** The previous Layer 3
   (`multi_po_dn.py`) grouped by *delivery note*. When delivery-note references
   did not line up across ERP and statement (the common case), it matched
   nothing, and the earlier 1:1 layers compared individual ERP delivery rows
   against a combined statement line — producing **false quantity discrepancies**.

2. **An undocumented Layer 2.5 (`aggregate_match.py`) overlapped and could mask
   real discrepancies.** It groups by PO (pass 1) and PO+material (pass 2), sums,
   and accepts a group if quantity **or** amount agrees (qty ±0.5% **or** amount
   ±1%). Critically, its `_emit_aggregate_matches` hardcodes `status="matched"`
   for everything — **it never emits a discrepancy**. On real data it produced 123
   matches and 0 discrepancies. Because it ran *before* Layer 3, any group it
   consumed could hide a genuine quantity/amount mismatch.

## Decision

### 1. Rewrite Layer 3 as multi-delivery aggregation (`multi_delivery.py`)

`run_multi_delivery_match` groups **both** sides by normalised
`(po_number, material_number)`, sums each side, and compares totals.

- **Normalisation** reuses Layers 1/2's `normalize_po_number` (float → int →
  string, whitespace stripped, PO revision suffixes dropped); material is
  stripped, mirroring Layer 1's exact key.
- **Tolerance:** quantity **and** amount must each be within ±0.5%
  (`price_tolerance_pct`) for `matched`. Quantity off → `quantity_over` /
  `quantity_under`; quantity ok but amount off → `price_higher` / `price_lower`.
  Checking amount (not quantity alone) prevents "right quantity, wrong money"
  from passing as matched, consistent with Layers 1, 2 and the prior Layer 3.
- **Price-consistency guard:** if the grouped ERP rows do not all share the same
  `po_price`, the group is **not** trusted as a clean aggregate. It is flagged as
  a discrepancy with `resolution_note = "price inconsistency across deliveries"`,
  while still surfacing the real aggregate quantity/amount deltas.
- **Loss-free emission:** every ERP row and every statement line in a grouped
  `(po, material)` appears in at least one result. The orchestrator consumes
  exactly what Layer 3 emits, so nothing is marked matched without a result and
  nothing is silently dropped.
- **One-sided groups** (a `(po, material)` present on only one side) are returned
  unmatched, so Layer 4 (AI) and the orchestrator tail record them with the
  missing side `NULL` (`missing_from_statement` / `missing_from_erp`).
- `match_type = "multi_delivery"`. The orchestrator's review bucket keeps the old
  `multi_po_dn` entry so any historical rows still classify correctly.

### 2. Run Layer 3 ahead of the aggregate fallback

The orchestrator waterfall is reordered so the discrepancy-aware Layer 3
adjudicates every `(po, material)` group **before** the always-"matched"
aggregate layer can mask it:

```
L1 exact → L2 fuzzy → L3 multi_delivery → L3.5 aggregate fallback → L4 AI → tail
```

- Layer 3 receives the imbalanced PO groups (from `_split_by_balance`) plus L1/L2
  leftovers — the input the aggregate layer used to receive.
- The aggregate layer (`aggregate_match.py`) is **unchanged in logic**. It is
  relabelled "Layer 3.5 / aggregate fallback" in comments and logs only and now
  runs on Layer 3's leftovers, where its distinct value is PO-level
  cross-material reconciliation (ERP and supplier using different material codes
  for the same parts).
- `_split_by_balance` routing is unchanged.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| **Remove the aggregate pass 2 only** (keep order) | Backfires: pass 1 (PO-level, looser, always-matched) runs first and would shadow Layer 3 *harder*. Reordering is the necessary move. |
| **Reorder + strip aggregate to pass 1** | More cleanup, but deletes code on a financial path; deferred to a follow-up. |
| **Merge everything into Layer 3, delete `aggregate_match.py`** | Largest change; reimplements the PO-level cross-material pass and touches `_split_by_balance` routing. Highest risk. |

**Chosen:** reorder only — smallest, fully reversible diff that guarantees no
group is silently marked matched when its totals disagree.

## Consequences

- **Positive:** Layer 3 owns `(po, material)` aggregation with real discrepancy
  detection, an ERP price-consistency guard, and a strict ±0.5% amount check.
  Multi-delivery groups are correctly attributed to `multi_delivery` rather than
  the always-matched `aggregate`.
- **Neutral / known debt:** the aggregate layer's pass 2 (PO+material) is now
  largely redundant — Layer 3 claims those groups first. It is left in place
  (harmless, starved) per the chosen "safest" option. Removing pass 2 and keeping
  only the PO-level pass is the natural follow-up.
- **Masking risk closed for the general case** even though it did not occur on the
  XFY201 dataset (measured masking = 0).

## Verification

- **Unit:** `tests/test_multi_delivery.py` (14 cases) covers aggregation,
  ±0.5% qty/amount boundaries, the price-inconsistency path (incl. multi-line,
  no data loss), one-sided groups, and PO float/whitespace normalisation.
- **Integration:** `tests/test_orchestrator_layer_order.py` seeds a group whose
  quantities reconcile but whose amount is +0.8% (inside the aggregate layer's 1%,
  outside Layer 3's 0.5%). It is RED under the old order (masked as
  `aggregate`/matched) and GREEN under the new order (`multi_delivery`/
  `price_higher`).
- **Suite:** full backend suite green (165 passed, 19 skipped).
- **Real data (XFY201 2026-03):** Layer 3 forms 38 `(po, material)` groups →
  35 matched, 3 genuine discrepancies (over-claims of 62.7% / 31.6% / 68.9% vs
  ERP). Old vs new order: identical verdicts (199 matched / 26 discrepancy rows);
  the only change is 123 rows moving from `aggregate/matched` to
  `multi_delivery/matched`. Reproduce with
  `.venv/bin/python -m scripts.recon_layer3_xfy201`.
