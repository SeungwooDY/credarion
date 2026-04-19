@AGENTS.md

Credarion — Project Summary
What It Is
An AI-powered accounting co-pilot built specifically for Asia-Pacific mid-market companies. Not a dashboard, not analytics — it actually does the accounting work: reconciliation, categorization, invoice processing, accruals, consolidation, forecasting, and month-end close.

The Problem It Solves
The pilot company — 梅州国威电子有限公司 (Méizhōu Guówēi Diànzǐ Yǒuxiàn Gōngsī) — is a manufacturing business that makes the problem visceral and real:

300 suppliers, 1,000+ delivery notes/month, 240–280 invoices/month — all manually processed
Supplier reconciliation takes 7 days per month in Excel, comparing ERP data against supplier-provided statements line by line
The bottleneck: ERP uses one system (SGWERP for supply chain, Kingdee K/3 for finance), suppliers each send statements in their own format — someone has to bridge that gap manually every month
Cross-border payments at ~17%, all requiring manual paperwork
Two roles doing this: an AP accountant and a cashier (出纳, Chūnà)

The CFO confirmed the pain hierarchy: monthly consolidation, cash visibility, rolling forecasts, and reconciliation are the biggest time sinks.

What You've Built So Far (Pre-Week 1)
You've collected real production data from the pilot company — a rare and genuinely valuable position. Files in hand:
FileWhat It Is3 月收货明细表 (Sān Yuè Shōuhuò Míngxì Biǎo)6,648-row ERP goods receipt export, March 20265 supplier reconciliation statements 奥雄 (Àoxióng), 鹏诚信 (Péngchéngxìn), 迈鼎 (Màidǐng), 展邦 (Zhǎnbāng), 丰裕达 (Fēngyùdá) — each in a different format 科目表 (Kēmù Biǎo)Kingdee K/3 Chart of AccountsK3 总账明细表 (K3 Zǒngzhàng Míngxì Biǎo)Kingdee General Ledger detail202601 月应付账款明细 AP ledger, January 2026ERP operation screenshotsHow the SGWERP reconciliation workflow looks in practiceDelivery note photosPhysical 送货单 (Sònghuòdān) samples
You also have a detailed Technical Handoff document that maps every column, every gotcha, and the exact 4-layer matching engine logic — built from analysis of the real files.

What You're Building First
The supplier reconciliation engine. Specifically:

Ingest ERP goods receipt data (SGWERP CSV export)
Ingest supplier statements (5 different formats, auto-detect headers, normalize columns)
Match on PO number + part number as primary keys
Flag discrepancies: quantity delta, price delta, missing from ERP, missing from statement
Output structured results via REST API — Richard builds the UI on top

Target: reduce reconciliation from 7 days to 1–2 days on real data, at the pilot company.

The Broader Vision (What Comes After)
Once reconciliation is validated:

Bank reconciliation, invoice processing + fapiao (发票, Fāpiào) OCR
Multi-entity consolidation (HK holding + China factory)
Accrual management, month-end close workflow
13-week rolling cash forecast + prescriptive WhatsApp alerts ("pay Supplier X now, delay Supplier Y by 15 days, draw from HSBC facility")
Margin intelligence: real-time P&L, cost driver breakdown, AR aging

The Team & Division of Labor

Richard — product + frontend (Next.js, Cursor)
Technical partner — backend (FastAPI, PostgreSQL, AWS ap-east-1)

Two people. No salary burn. The pilot is free, which is the right call — you need proof before you charge.

Target Market & Pricing
HK holding companies with Mainland China operations, $5M–$100M revenue, 2–5 legal entities, Kingdee-based finance teams doing manual Excel reconciliation.

Starter: $500/month (1 entity)
Growth: $1,200/month (up to 5 entities)
Enterprise: $2,500/month (unlimited)

Justified against $15–25K/month in finance labor costs. The math works if the product works.

Competitive Position

Mars/Minerva — US CPG only, doesn't operate in APAC. Not a threat yet.
Agicap — European, dashboard-only, no ERP write-back, no Asia support.
Your real moat: Kingdee/Yonyou integrations, APAC-native, actually writes to ERP, multi-currency multi-entity, WhatsApp-first alerts. None of that is easy to copy.
