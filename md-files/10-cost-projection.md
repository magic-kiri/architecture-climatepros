<!--
  §10 Cost Projection — SOURCE OF TRUTH for this section of the Word document.
  Edit here, then run: python3 scripts/build_docx.py

  `#` section title · `##` subsection (in Contents; bare `A `/`B `/`C `/`B C `
  prefix = coloured badge) · `###` sub-subsection · pipe tables get house
  style automatically · ``` fences ``` = mono cost-formula box ·
  `> quote` = copper callout.

  Organized by infra component across the unified platform, not by use case.
-->

# 10. Cost Projection

One shared infra bill across A/B/C — same compute tiers, same fixed floor. A use case only shows up as a load driver (dispatch hours-on, B+C call volume), not a separate section.

Figures below are for **one environment only** (e.g. prod). Dev/Staging add cost on top — each environment duplicates this bill.

> **Pending re-pricing:** Azure lines (Container Apps, vector store, Monitor) below use carried-over AWS rate-card estimates, not real Azure prices yet. Cosmos DB (Mongo vCore) is a real Azure quote, unverified for region/tier.

## Compute Sizing

New tiers scale horizontally (more replicas), not vertically (bigger box). Baseline 0.5 vCPU / 1 GB handles 60+ concurrent dispatches per instance.

| Component | Instance size | Scaling | Notes |
| --- | --- | --- | --- |
| Dispatch workers (ECS Fargate) — AWS | 0.5 vCPU / 1 GB | Scale 0–1 on Auto-Dispatch toggle | 60+ concurrent dispatches/instance |
| AI server (FastAPI) — Azure | 0.5 vCPU / 1 GB | Scale 1–N on request concurrency | Shared B & C; min 1 replica, no cold-start |
| ElastiCache for Redis — AWS | Managed tier | Fixed; sized to queue depth | No-eviction, persistence on |
| Vector store — Azure | Managed, serverless/free-tier scale | 3-4K embeddings — small, flat | Parts index (C); optional similar-incident index (B) |
| MongoDB (Cosmos DB for MongoDB vCore) — Azure | M10 tier (2 vCore / 8 GB) | Fixed tier; step up manually, not autoscale | AI stack's own store — summaries, part results, llm_calls, evals; no SQL Server coupling |

## Cost Formulas

### AWS Fargate — dispatch workers

```
per_task_hour = (vCPU x rate_vcpu) + (GB x rate_mem)
monthly_cost  = N x H x 30 x per_task_hour

vCPU = 0.5, rate_vcpu = $0.04048/hr
GB   = 1,   rate_mem  = $0.004445/hr
  -> per_task_hour = $0.024685

N = tasks (0 or 1 — scale-to-zero)
H = hours ON per day
```

### Fixed / near-fixed lines

```
ElastiCache Redis   = $0.032/hr x 730 hr  = ~$23.36/mo  (fixed, no-eviction)
SNS push = 500 dispatches/day x 5 techs x 30 = 75,000 pushes/mo
         = 75,000 x $0.50/1,000,000 = ~$0.04/mo
Container Apps (AI) = $20 - $40/mo   (1-2 replicas, 0.5 vCPU / 1 GB)
Vector store        = ~$5/mo flat    (3-4K embeddings, serverless/free-tier scale)
Azure Monitor + OTel= $15 - $30/mo
Cosmos DB Mongo(vCore) M10 = $0.129/hr x 730 hr = ~$94/mo flat
```

## Unified Monthly Cost by Scenario

| Component | Light (2h/day) | Typical (8h/day) | Heavy (24×7) |
| --- | --- | --- | --- |
| Dispatch workers — Fargate | ~$1.48 | ~$5.92 | ~$17.77 |
| AI server — Container Apps | ~$20 | ~$30 | ~$40 |
| Redis (fixed) | ~$23.36 | ~$23.36 | ~$23.36 |
| SNS push | ~$0.04 | ~$0.04 | ~$0.04 |
| Vector store (flat) | ~$5 | ~$5 | ~$5 |
| Monitor + OTel | ~$15 | ~$22 | ~$30 |
| MongoDB — Cosmos DB vCore (flat) | ~$94 | ~$94 | ~$94 |
| Variable — per B+C call | < $1 | ~$2 – $5 | ~$10 – $25 |
| **Total/mo (est.)** | **~$159** | **~$182 – $185** | **~$220 – $235** |

Fixed floor (Redis + vector store + Mongo + Monitor) ≈ $137–$152/mo regardless of traffic; only Fargate + Container Apps + variable calls scale down toward zero.

## Database & Cross-Cloud Egress

SQL Server stays on AWS, unchanged — no incremental cost. Only cross-cloud line: the AWS→Azure AI request/response (B/C egress).

| Component | Cloud | ~ Monthly |
| --- | --- | --- |
| AWS SQL Server | AWS | Existing, sunk — no incremental cost |
| Cross-cloud egress (AWS → Azure AI calls) | AWS egress | TBD — needs a traffic estimate; get an AWS Data Transfer OUT quote once real volume is known |
