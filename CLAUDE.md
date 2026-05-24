@AGENTS.md

# Credarion — Project Summary

## What It Is
An AI-powered accounting co-pilot built specifically for Asia-Pacific mid-market companies. Not a dashboard, not analytics — it actually does the accounting work: reconciliation, categorization, invoice processing, accruals, consolidation, forecasting, and month-end close.

## Pilot Company
梅州国威电子有限公司 (Méizhōu Guówēi Diànzǐ Yǒuxiàn Gōngsī) — a manufacturing business:
- 300 suppliers, 1,000+ delivery notes/month, 240–280 invoices/month
- Supplier reconciliation takes 7 days/month in Excel
- ERP: SGWERP (supply chain) + Kingdee K/3 (finance)
- Target: reduce reconciliation from 7 days to 1–2 days

## Architecture

### Backend (`backend/`)
- **Framework**: FastAPI + SQLAlchemy 2.0 + Alembic
- **Database**: PostgreSQL (Supabase), SQLite for tests
- **AI**: Anthropic Claude API (Haiku for OCR + AI matching)
- **Python**: 3.13, managed via `.venv/`

### Frontend (`frontend/`)
- **Framework**: Next.js 16.2.2 (App Router) + React 19 + TypeScript
- **Styling**: Tailwind CSS v4
- **API Proxy**: next.config.ts rewrites `/api/*` → `http://localhost:8000/api/*`

### Key Directories
```
backend/
  app/
    models.py           # 13 SQLAlchemy ORM models
    config.py           # Pydantic Settings
    db.py               # Engine, SessionLocal, get_db()
    main.py             # FastAPI app, 5 routers
    routers/            # erp, statements, orgs, reconciliation, invoices
    reconciliation/     # 4-layer matching engine + orchestrator + schemas
    ingestion/          # GRN + statement ingestion pipelines
    invoicing/          # OCR extraction + file storage + supplier matcher + schemas
  db/migrations/versions/  # 0001–0004
  tests/                   # 150+ tests

frontend/
  app/
    page.tsx                # Dashboard
    ingestion/page.tsx      # GRN + statement upload
    reconciliation/page.tsx # Run reconciliation, view results
    invoices/page.tsx       # Upload, extract, list invoices
    invoices/[id]/page.tsx  # Invoice detail with edit + status transitions
    settings/page.tsx       # Org management + recon config
    components/             # Sidebar, PageHeader, StatusBadge
    lib/api.ts              # Fetch helper
```

## Implementation Status (as of 2026-04-20)

| Week | Scope | Status |
|------|-------|--------|
| 1–2 | Foundation + Data Ingestion | Complete |
| 3 | 4-Layer Matching Engine | Complete |
| 4 | Discrepancy Detection | Complete |
| 5 | Reconciliation UI | Complete |
| 6 | Testing (150+ tests) | Complete |
| 7 | Invoice Processing (OCR) | Complete |

### What's Built
- **Data Ingestion**: GRN CSV/XLSX upload with SSE progress, supplier statement ingestion with auto header detection + column mapping
- **Reconciliation Engine**: exact match → fuzzy PO → multi-PO delivery note → AI (Claude Haiku). Configurable tolerances. Waterfall orchestrator.
- **Discrepancy Detection**: qty over/under, price higher/lower, missing from ERP, missing from supplier. Resolve + bulk-resolve with audit trail.
- **Invoice Processing**: Batch upload → OCR extraction (Claude Vision) → per-field confidence scoring → supplier auto-matching → status workflow (received→extracted→matched→approved→paid)
- **Frontend**: 6-page Next.js skeleton with sidebar nav, all wired to backend API

### What's Next
- Wire resolve/bulk-resolve into reconciliation UI (backend endpoints exist)
- Test OCR extraction with real fapiao samples
- Run reconciliation against all 5 pilot suppliers
- Bank reconciliation + fapiao cross-referencing

## Running Locally

```bash
# Backend (port 8000)
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (port 3000)
cd frontend && npm run dev

# Tests
cd backend && .venv/bin/python -m pytest tests/ -v
```

## Team
- **Richard** — product + frontend (Next.js)
- **Technical partner** — backend (FastAPI, PostgreSQL)

## Target Market
HK holding companies with Mainland China operations, $5M–$100M revenue, Kingdee-based finance teams.
- Starter: $500/month (1 entity)
- Growth: $1,200/month (up to 5 entities)
- Enterprise: $2,500/month (unlimited)
