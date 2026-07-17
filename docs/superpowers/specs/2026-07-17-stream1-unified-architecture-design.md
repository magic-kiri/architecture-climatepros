---
doc_type: design-spec
topic: stream1-unified-architecture
status: Approved
generated_at: 2026-07-17
author: kiriti.m@techjays.com (via Claude Code)
---

# Stream 1 — Unified Full Architecture · Design Spec

## Goal

Produce a single, self-contained document that merges the three Stream 1 use-case
architectures — **A · Auto-Dispatch**, **B · Job Summarisation Copilot**,
**C · Technician Parts Finder** — into one "Stream 1" full architecture, at full
fidelity, with a committed **Azure-first** cloud placement (one cross-cloud
exception: the SQL Server database stays on AWS).

## Deliverable

- **New file:** `stream1-unified-architecture.html` at repo root.
- Standalone HTML with all CSS inlined in a `<style>` block (repo convention — no
  external assets, opens directly in a browser).
- Reuses the existing visual language: `:root` palette (`--blue` / `--amber` /
  `--green` / `--purple` soft+line pairs), chip / card / flow-step / diagram-frame
  conventions from the source docs.
- Source docs (`system-design.html`, `usecase-b-architecture.html`,
  `usecase-C-system-design.html`, `unified-hld.html`) are **left untouched**.

## Source material

| Use case | Source file | Diagram type |
|---|---|---|
| A · Auto-Dispatch | `system-design.html` | HTML/CSS `diagram-frame` (no SVG) |
| B · Job Summarisation | `usecase-b-architecture.html` | 19 SVGs + HTML flow steps |
| C · Parts Finder | `usecase-C-system-design.html` | 1 SVG + 13 tables |
| Unified HLD | `unified-hld.html` | one SVG (`viewBox 0 0 1200 1020`) + inventory + AWS/Azure toggle |
| Problem framing | `problem-statement.html` | — |

## Cloud transformation rules (applied throughout — text, diagrams, inventory, cost)

Commit to **Azure**; drop the AWS/Azure toggle entirely. Render one Azure-first view.

| Concern | Current (source docs) | Unified doc (target) |
|---|---|---|
| Existing FieldJetX compute | AWS EC2 (one host, both .NET services) | **Azure VM** |
| .NET Legacy API + Microservices API | on AWS EC2 | on **Azure VM** (unchanged code; + AI proxy route + scale monitor) |
| Web + Mobile (Flutter) clients | clients | unchanged |
| Dispatch queue | Redis Stream (ElastiCache) | **Azure Cache for Redis** (Streams, consumer groups) |
| Worker pool | AWS ECS Fargate (scale 0–1) | **Azure Container Apps** (scale 0–1) |
| Central AI service | FastAPI on AWS ECS Fargate | FastAPI on **Azure Container Apps** |
| Vector store | "Vector DB" / S3 Vectors (C) | **Azure-hosted vector store** (reconcile C's S3 Vectors reference) |
| Push to device | Amazon SNS → APNs/FCM | **Azure Notification Hubs** → APNs/FCM |
| Logs / metrics | CloudWatch | **Azure Monitor** |
| **SQL Server DB (system of record)** | AWS | **STAYS on AWS** — sole cross-cloud dependency |
| Model layer | on-prem CP Office: LiteLLM + self-hosted qwen3-vl-moe (vLLM) + bge-m3 embedding + Gemini fallback | **unchanged, on-prem** |

**Cross-cloud call-out (required):** Azure compute (Container Apps, VM) reaches the
AWS-hosted SQL Server. Note the implications explicitly in the Infrastructure
section — network path, latency, egress/data-transfer cost, and that the DB is the
single point where the two clouds meet.

**Known contradiction to flag in the doc:** current source docs place the existing
FieldJetX platform on AWS EC2. This spec treats "existing platform is Azure" as the
decided target state per stakeholder instruction and rewrites accordingly. A short
note in the Overview records that the existing-platform cloud was restated to Azure.

## Document outline (concern-first; A / B / C appear as subsections within each concern)

1. **Stream 1 Overview** — one job, three bottlenecks (from `problem-statement.html`);
   A is a deterministic algorithm (no LLM, explainable), B and C are AI with
   technician override. Records the Azure restatement note.
2. **High-Level Architecture** — see dedicated structure below.
3. **Technology Stack** — one unified table, columns for A | B | C, shared rows
   (Flutter, FastAPI, Azure VM/.NET, AWS SQL Server, Azure Container Apps) called out
   as shared.
4. **Infrastructure** — Azure component inventory + the AWS SQL Server cross-cloud note.
   Carry the unified-HLD "What We Have vs What We Introduce" inventory, Azure-transformed.
5. **Operational Flows** — A: dispatch board → rank → offer cascade → assign;
   B: summarise + copilot suggestions; C: four-source find → allocate. Lift source flow
   diagrams.
6. **Core Logic (per use case)** — A: ranking weighted-sum formula + configurable
   weights; B: the Summarise pipeline + retrieval; C: matching, exact scoring, and the
   self-learning indexing loop. Full fidelity — formulas and pipeline steps preserved.
7. **Data & Schema** — A: Redis data structures; B: the `ai.*` schema (ER diagram);
   C: vector store + system-of-record tables.
8. **API Reference** — A | B | C endpoints, full parameter lists preserved.
9. **Observability & Evals** — unified OpenTelemetry tracing + Azure Monitor logs
   (from unified HLD's observability block) + B's evals section.
10. **Cost Projection** — A | B | C line items, re-priced to Azure equivalents; keep
    line-item granularity.
11. **Onboarding & Fault Tolerance** — per use case (A and B both have these sections;
    add C where applicable).
12. **Non-goals & PII** — C's PII inventory + cross-use-case non-goals (A: not route
    optimization; B: never fabricates, never blocks Save; C: no price ranking, no ordering).

## HLD section structure (explicit stakeholder requirement)

**§2 renders in this order:**

- **2a — Unified diagram first.** The `unified-hld.html` SVG, Azure-transformed
  (apply the transformation rules above), toggle removed, SQL Server DB node marked
  **AWS**. This is the single combined picture of the whole Stream 1 flow.
- **2b — Three detailed HLDs, one by one.** For each use case in order A → B → C:
  a short "what this use case adds to the platform" intro, then that use case's own
  architecture diagram lifted from its source doc and Azure-transformed.
  - A: the `diagram-frame` HTML/CSS architecture diagram from `system-design.html`.
  - B: the primary architecture SVG from `usecase-b-architecture.html`.
  - C: the architecture SVG from `usecase-C-system-design.html`.

## Merge depth

**Full fidelity.** Carry over all substantive detail: A's ranking formula, B's
`ai.*` schema and summarise pipeline, C's scoring and supplier contract notes, full
API parameter lists, and cost line items. The unified doc is intended to stand alone;
source docs become redundant reference. Expect a large single file (~260KB of source
merged) — acceptable and expected.

## Build approach

- Author the new HTML fresh, reusing source SVG / diagram markup where liftable,
  transformed AWS→Azure per the rules table.
- Keep everything inline and self-contained.
- Preserve numbered `<h2>` sectioning and the source palette.

## Out of scope

- Modifying the source docs or `CLAUDE.md`.
- Re-costing beyond swapping AWS line items for Azure equivalents (no new pricing research).
- Redesigning any diagram from scratch (lift + transform only).
- Building the AWS/Azure toggle (explicitly dropped).

## Success criteria

- One standalone HTML file renders the full Stream 1 architecture.
- HLD section shows unified diagram first, then A, B, C detailed diagrams.
- Every component reads as Azure except the SQL Server DB (AWS), with the cross-cloud
  dependency explicitly noted.
- No detail lost from the three source designs (full fidelity).
- No AWS/Azure toggle; single committed view.
