# Credarion — Build Progress

Living document. Update at the end of every working session. Read this first in any new conversation before touching code.

See also: `CLAUDE.md` (product summary), `AGENTS.md` (Next.js warning), and the Technical Build Handoff (April 2026) which defines the authoritative schema and matching logic for the reconciliation wedge.

---

## Current phase

**Phase 1 — Foundation + Real Data (Weeks 1–2)**
Building the supplier reconciliation wedge. Nothing else until it works.

## Team

- **Seungwoo (user)** — backend partner. FastAPI, PostgreSQL, schema, matching engine.
- **Richard** — product + frontend (Next.js, Cursor). Not active in this repo yet.

## Pilot company

梅州国威电子有限公司 (Meizhou Guowei Electronics). Single entity. Kingdee K/3 for finance, SGWERP (custom) for supply chain. ~300 suppliers, ~1,000 delivery notes/month, 240–280 invoices/month. Reconciliation currently takes 7 days in Excel; target is 1–2 days.

---

## Repo layout (monorepo)

```
credarion/
├── frontend/          Next.js (boilerplate, untouched — Richard's territory)
├── backend/           FastAPI + SQLAlchemy 2.0 + Alembic
│   ├── app/
│   │   ├── main.py    FastAPI entrypoint, /health, router wiring
│   │   ├── config.py  pydantic-settings (+ optional ANTHROPIC_API_KEY)
│   │   ├── db.py      engine + Base + session
│   │   ├── models.py  7 ORM models (added SupplierColumnMapping)
│   │   ├── ingestion/
│   │   │   ├── header_detection.py   Auto-detect header row in supplier statements
│   │   │   ├── column_mapping.py     Three-tier mapper (alias → LLM → human)
│   │   │   ├── cleaning.py           PO/qty/date normalization, summary row filter
│   │   │   └── statement_ingestor.py Orchestrator: read → detect → map → clean → insert
│   │   └── routers/
│   │       └── statements.py         POST /upload, PUT/GET /mappings
│   ├── db/migrations/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_supplier_column_mappings.py
│   ├── tests/
│   │   └── test_ingestion.py         37 tests (header, mapping, cleaning, e2e)
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── .env.example
├── data/samples/      gitignored, real pilot data (see below)
├── AGENTS.md
├── CLAUDE.md
└── PROGRESS.md        (this file)
```

## Stack decisions (locked)

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic, psycopg3, pandas (+ openpyxl for .xlsx, xlrd for .xls)
- **Database**: PostgreSQL
- **Database hosting**: Supabase (project ref: `mqvgqbxexprpykqjepsd`). Uses pooler connection string. Password was reset 2026-04-12 after accidental exposure.
- **Hosting**: AWS ap-east-1 (Hong Kong) — not yet provisioned
- **Frontend**: Next.js (fresh create-next-app, not yet touched). AGENTS.md warns this is a non-standard Next.js build — read `frontend/node_modules/next/dist/docs/` before writing any Next code.
- **Language**: English-first UI, toggleable 简体中文 later.

---

## Done

### Monorepo + backend foundation (2026-04-08)

- Moved boilerplate Next.js files into `frontend/`
- Created `backend/` scaffold: FastAPI `/health`, pydantic-settings config, SQLAlchemy Base + session, `.env.example`
- Created Alembic setup (`alembic.ini`, `db/migrations/env.py`, initial revision)
- Wrote SQLAlchemy 2.0 models for all 6 tables
- Wrote initial Alembic migration `0001_initial_schema.py` implementing the full wedge schema
- Updated root `.gitignore` for monorepo (Python + Next.js)

**Not committed yet.** User to review before first commit.

### Supplier statement ingestion pipeline (2026-04-12)

Full ingestion pipeline for supplier reconciliation statements:

- **Header detection** (`header_detection.py`): Scans rows 0–15 for Chinese keywords (订单 + 数量 required). Verified against all 5 supplier files — Aoxiong row 5, Pengchengxin row 7, Maiding row 8, Fengyuda row 9, Zhanbang row 9.
- **Column mapping** (`column_mapping.py`): Three-tier system:
  - Tier 1 — Alias dictionary covering all 5 known suppliers (handles full-width parens, whitespace normalization)
  - Tier 2 — Claude Haiku LLM fallback for unknown suppliers
  - Tier 3 — Human review flag with partial mapping saved
  - Caching: mappings stored in `supplier_column_mappings` table, checked before running tiers
- **Data cleaning** (`cleaning.py`): PO normalization (`"428759.0"` → `"428759"`), thousands separator removal, Decimal conversion, date parsing (ISO/slash/M-D-Y), summary row filtering (合计/总计/小计 including spaced variants like `合    計`), trailing whitespace stripping on part numbers
- **Orchestrator** (`statement_ingestor.py`): read → detect format → detect header → check cache → map columns → clean → create SupplierStatement → bulk insert StatementLineItem rows → return IngestionResult
- **API endpoints** (`routers/statements.py`):
  - `POST /api/v1/statements/upload` — multipart file upload + supplier_id + period → ingest
  - `PUT /api/v1/statements/mappings/{mapping_id}` — manual mapping confirmation (Tier 3)
  - `GET /api/v1/statements/mappings/{supplier_id}` — check current mapping
- **Database**: `SupplierColumnMapping` model + migration `0002_supplier_column_mappings`
- **Dependencies**: Added `anthropic>=0.40.0` to pyproject.toml, optional `ANTHROPIC_API_KEY` in config
- **Tests**: 37 tests passing — header detection (all 5 suppliers), Tier 1 alias mapping, PO/qty/date normalization, summary row filtering, end-to-end cleaning

**Correction from handoff**: PO 428759 for Aoxiong has **29** line items in the actual data, not 24 as stated in the handoff §4.

### Schema — approved deltas from the handoff

The Technical Build Handoff (April 2026) is the authoritative spec. These three deltas were discussed and approved by the user:

1. **`erp_records.quantity` and `statement_line_items.quantity` are `NUMERIC(14,3)`**, not `INTEGER`. SGWERP has no integer constraint and supplier statements are free-form. Prevents a painful future migration.
2. **`raw_row JSONB` column** added to `erp_records` and `statement_line_items`. Preserves the original parsed row for audit and debugging without re-parsing source files. ~500 bytes/row, ~3 MB/month — negligible.
3. **No `delivery_notes` table.** Multi-PO delivery notes are handled at match time in Layer 3. `dn_no` lives as a column on `erp_records`.

Also confirmed:
- **Multi-entity**: `org_id` only for now. No `entities` table. When HK holding + China factory arrives, add `entities` as child of `organizations` and backfill.
- **Audit log**: Not in v1. Add in Week 5 alongside resolve-discrepancy UI.
- **Supplier canonical key**: `vend_no` from SGWERP (e.g. `SDD201`). Stored on `suppliers.vendor_code`, unique per `(org_id, vendor_code)`.

### Schema — tables (mirrors handoff §3 + deltas)

1. `organizations` — tenant boundary
2. `suppliers` — one row per vendor (`vendor_code` = SGWERP `vend_no`)
3. `erp_records` — one row per SGWERP GRN line, with `raw_row JSONB`. Indexed on `(supplier_id, po_number, material_number)` for Layer 1 matching, plus individual indexes on `po_number`, `material_number`, `delivery_note`.
4. `supplier_statements` — one row per uploaded statement file
5. `statement_line_items` — parsed rows from supplier statements, with `raw_row JSONB`
6. `reconciliation_results` — one row per match attempt. `match_type`: exact | fuzzy | multi_po_dn | ai | unmatched. `status`: matched | discrepancy | resolved.

---

## Pilot data on hand (`data/samples/`, gitignored)

All in `data/samples/erp/` (user imported everything into one folder; that's fine):

| File | What it is | Status for wedge |
|---|---|---|
| `March Goods Receipt Detail.xlsx - GRN.csv` | **SGWERP GRN — the gold file.** 6,648 rows, 43 columns. 214 suppliers, 1,395 POs, 3,421 part numbers. RMB/USD/HKD. | **Primary input to matching engine.** |
| `Guowei-Aoxiong March 2026 Reconciliation.xlsx - Sheet1.csv` | 奥雄 supplier statement. Header at row 5. | Matching test input |
| `Guowei Electronics March Reconciliation Statement (Supplier_Pengchengxin).xlsx - 鹏诚信.csv` | 鹏诚信. Header at row 7. Qty has thousands separators (`"10,000"`). | Matching test input |
| `Maiding-Guowei March 2026 Reconciliation Statement.xlsx - 对账.csv` | 迈鼎. Header at row 8, wraps across 2 rows. Has 上月结余/本月实付 totals. | Matching test input |
| `Meizhou Guowei ... (Supplier_ Zhanbang).xls - 对账单.csv` | 展邦. Header at row 9. | Matching test input |
| `Meizhou Guowei ... (Supplier_ Fengyuda).XLS - 国威3月份.csv` | 丰裕达. Header at row 9. Trailing spaces in part#. | Matching test input |
| `Kingdee K3 General Ledger Detail.xls - 会计分录序时簿.csv` | K3 GL journal (not GRN). Forward-filled headers. Multi-currency. | Not on wedge critical path. Useful later for close/audit. |
| `January 2026 Accounts Payable Detail.xls - 明细分类账.csv` | K3 AP subledger, Jan 2026. Free-text supplier names in 摘要. | Later — payment workflow. |
| `Chart of Accounts.xls - 科目.csv` | K3 科目表, 20 cols. | Reference lookup. |

**Validated anchor**: Handoff §4 says for supplier 奥雄 (`SDD201`), PO 428759: 24 of 24 ERP part numbers match the statement exactly; 1 extra line on statement is a genuine discrepancy. **This is the first unit test for the matching engine.**

### Known data gotchas (from handoff §5, all must be handled in ingestion)

- **PO number: float vs string.** Supplier statements store `428759.0`; ERP stores `428759`. Normalize: cast to int then str.
- **Header row varies** (rows 5–10). Detect by scanning for 2+ of: 订单, 数量, 单价, 金额, 物料.
- **Column names are inconsistent across suppliers.** See handoff §2 table. AI column mapper required.
- **Part number column** can be named 产品名称, 客户料号, 物料编码, 产品型号. All contain format `XXX*XXXX*X*XXX`.
- **Mixed formats**: .xlsx (openpyxl) and .xls (xlrd).
- **Duplicate PO+PN in ERP** (different delivery dates = separate GRNs). Match must use GRN number or date proximity as tiebreaker.
- **`grn_accept` not `grn_receive`.** Accepted quantity is the match value.
- **`po_price` not `unit_price`.** `po_price` is pre-tax and matches supplier statements. `unit_price` is post-VAT.
- **Summary/total rows at bottom of statements** (合计, 总计). Filter before matching.
- **Encoding**: UTF-8 everywhere. No GBK issues.

### Not yet received

- **Fapiao invoice samples** (needed before Week 7 for OCR pipeline)
- **Delivery note photos** (low priority; keep in native JPG/PNG, not PDF, when they arrive)
- **March AP ledger** (requested, only have January 2026)

---

## Next up

**Immediate**:
1. Reset Supabase database password (exposed in chat 2026-04-12), update `.env` with new pooler connection string.
2. Apply migrations to database: `.venv/bin/alembic upgrade head` (0001 + 0002)
3. **SGWERP GRN importer** — parse `March Goods Receipt Detail.xlsx - GRN.csv` → create/upsert suppliers (on `vend_no`), insert `erp_records`. Store `raw_row`. Handle date parsing, currency, VAT. Target: 6,648 rows → database cleanly.
4. Upload all 5 supplier statements via the new POST endpoint, verify line items land correctly.

**Week 3**: Matching engine Layers 1 + 2 (exact + fuzzy PO).

## Open questions / decisions deferred

- **Auth** for the API (not needed until Richard starts wiring the frontend; placeholder OK)
- **S3 bucket** in ap-east-1 for raw uploaded files (needed for `supplier_statements.file_url`; local filesystem fine for dev)
- **Claude API key management** — `ANTHROPIC_API_KEY` is now optional in config. Only needed if Tier 1 alias mapping fails for a new supplier. Store in `.env` when needed.
- **Kingdee version confirmation** — handoff says K/3. Not blocking yet.
- **Aoxiong PO 428759 count discrepancy** — handoff says 24 lines, actual data has 29. Need to verify whether this is a data issue or handoff error.
