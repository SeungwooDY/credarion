-- Manual, idempotent application of migration 0006 (accounting periods).
--
-- WHY THIS EXISTS:
-- The shared Supabase DB's alembic_version is "0006", but that marker belongs to
-- an UNCOMMITTED auth migration applied by the backend partner (it created the
-- `accounts` and `users` tables). Our period migration also got id 0006, so a
-- normal `alembic upgrade head` would no-op, and `alembic stamp 0005` would
-- overwrite the partner's marker. To avoid touching the partner's migration
-- state, this script applies ONLY the additive period schema and does NOT modify
-- alembic_version. The alembic numbering is reconciled with the partner later.
--
-- It is purely additive and idempotent (IF NOT EXISTS / ON CONFLICT), so it is
-- safe to run once or repeatedly, and it never touches accounts/users or data.
--
-- HOW TO RUN: paste into the Supabase SQL editor (or psql) against the dev DB.

BEGIN;

-- 1) accounting_periods registry --------------------------------------------
CREATE TABLE IF NOT EXISTS accounting_periods (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    period      varchar NOT NULL,
    label       varchar NOT NULL,
    status      varchar NOT NULL DEFAULT 'open',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_accounting_periods_org_period UNIQUE (org_id, period)
);

-- 2) period tags on erp_records + invoices -----------------------------------
ALTER TABLE erp_records ADD COLUMN IF NOT EXISTS period varchar;
CREATE INDEX IF NOT EXISTS ix_erp_records_period ON erp_records (period);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS period varchar;
CREATE INDEX IF NOT EXISTS ix_invoices_period ON invoices (period);

-- 3) backfill the period tags from existing dates ----------------------------
UPDATE erp_records SET period = to_char(grn_date, 'YYYY-MM') WHERE period IS NULL;
UPDATE invoices SET period = to_char(invoice_date, 'YYYY-MM')
 WHERE period IS NULL AND invoice_date IS NOT NULL;

-- 4) seed the registry from every distinct (org, period) already in the data -
INSERT INTO accounting_periods (id, org_id, period, label, status, created_at, updated_at)
SELECT gen_random_uuid(),
       src.org_id,
       src.period,
       to_char(to_date(src.period || '-01', 'YYYY-MM-DD'), 'FMMonth YYYY'),
       'open',
       now(),
       now()
FROM (
    SELECT DISTINCT org_id, period FROM erp_records WHERE period IS NOT NULL
    UNION
    SELECT DISTINCT s.org_id, ss.period
      FROM supplier_statements ss JOIN suppliers s ON s.id = ss.supplier_id
     WHERE ss.period IS NOT NULL
    UNION
    SELECT DISTINCT s.org_id, rr.period
      FROM reconciliation_runs rr JOIN suppliers s ON s.id = rr.supplier_id
     WHERE rr.period IS NOT NULL
    UNION
    SELECT DISTINCT org_id, period FROM invoices WHERE period IS NOT NULL
) AS src
ON CONFLICT (org_id, period) DO NOTHING;

COMMIT;
