# Stream 1 Unified Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `stream1-unified-architecture.html` — a single self-contained doc merging use cases A/B/C at full fidelity, Azure-first, with SQL Server DB on AWS.

**Architecture:** One standalone HTML file, all CSS inlined, built section-by-section. Concern-first outline with A|B|C subsections. HLD section shows a unified diagram first, then A/B/C detailed diagrams lifted from source docs and Azure-transformed. No AWS/Azure toggle.

**Tech Stack:** Hand-authored HTML + inline CSS. No build tooling, no framework, no tests runner. Verification = `grep` structural checks + `open` in browser.

**Spec:** `docs/superpowers/specs/2026-07-17-stream1-unified-architecture-design.md` — read it before starting; the cloud-transformation rules table is normative.

## Global Constraints

- Output file: `stream1-unified-architecture.html` at repo root. Single file, self-contained, all CSS inline. No external assets (repo convention — must open standalone).
- **BUILD MODEL (from Task 9 onward):** the output HTML is **generated** by `python3 scripts/build.py` from fragment files in `sections/` (`_head.html` + `_style.css` + `_body-open.html` + `01.html`…`12.html`, concatenated in order). **Never hand-edit `stream1-unified-architecture.html`** — edit the matching `sections/NN.html` fragment, then run `python3 scripts/build.py`, then verify on the built file. Section `#sN` lives in `sections/NN.html` (e.g. `#s7` → `sections/07.html`). Put section-specific CSS in a `<style>` block at the top of that fragment (browsers accept in-body `<style>`); keep `_style.css` for shared/base rules only. Each fragment is exactly its `<section id="sN">…</section>` block.
- Source docs `system-design.html`, `usecase-b-architecture.html`, `usecase-C-system-design.html`, `unified-hld.html`, `problem-statement.html` are READ-ONLY. Never modify them.
- **Cloud transform (apply to every lifted fragment — text, diagram labels, inventory, cost):**
  - AWS EC2 → **Azure VM**; ECS Fargate / ECS Tasks → **Azure Container Apps**; Redis Stream/ElastiCache → **Azure Cache for Redis**; Amazon SNS → **Azure Notification Hubs**; CloudWatch → **Azure Monitor**; S3 Vectors / "Vector DB" → **Azure-hosted vector store**.
  - **SQL Server database STAYS on AWS** — the only AWS component. Every other component is Azure.
  - Model layer unchanged (on-prem CP Office: LiteLLM + qwen3-vl-moe/vLLM + bge-m3 + Gemini fallback).
- No AWS/Azure toggle. Single committed Azure view.
- Preserve source palette: `:root` vars `--blue`/`--amber`/`--green`/`--purple` soft+line pairs; chip/card/flow-step/diagram-frame classes.
- Numbered `<h2>` sections. Full fidelity — no detail dropped, no summarising of tables/formulas/API params.
- Commit after each task with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Scaffold the document shell

**Files:**
- Create: `stream1-unified-architecture.html`

**Interfaces:**
- Produces: the base HTML skeleton — `<style>` block with the merged `:root` palette and shared component classes (`.wrap`, `.hero`, `section`, `h2`, `.chip`, `.card`, `.inv`, `.count`, `diagram-frame`, `flow-step`, `.pill`), plus an empty numbered-section scaffold (`<section id="s1">`…`<section id="s12">`) that later tasks fill.

- [ ] **Step 1: Copy the unified-hld `:root` palette + base body/hero/section/h2 CSS** into a new `<style>` block. Extend the palette with the green/red soft+line pairs from `problem-statement.html` (`--green-soft`/`--green-line`, `--red-soft`/`--red-line`, `--blue-soft`/`--blue-line`, `--amber-soft`/`--amber-line`) so lifted fragments render.

- [ ] **Step 2: Add the hero header** — `<h1>ClimatePros · Stream 1 — Unified Architecture</h1>` + subtitle: "Three use cases, one job · Auto-Dispatch (A) · Job Summarisation (B) · Parts Finder (C) · Azure-first, SQL Server on AWS".

- [ ] **Step 3: Add 12 empty numbered `<section>` placeholders** with `<h2>` titles matching the spec outline (1 Stream 1 Overview … 12 Non-goals & PII). Each section body: `<!-- filled in Task N -->`.

- [ ] **Step 4: Verify structure**

Run: `grep -c '<section' stream1-unified-architecture.html`
Expected: `12`

Run: `open stream1-unified-architecture.html`
Expected: hero + 12 empty section headings render, no console-visible layout break.

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Scaffold Stream 1 unified architecture doc shell"
```

---

### Task 2: Section 1 — Stream 1 Overview

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s1`)
- Read: `problem-statement.html`

**Interfaces:**
- Consumes: doc shell from Task 1.
- Produces: filled `#s1`.

- [ ] **Step 1: Lift the three-use-case framing** from `problem-statement.html` — the "one job, three bottlenecks" narrative + the A=deterministic-algorithm / B,C=AI-with-override distinction. Condense the per-UC flow cards into a compact intro row (this is the overview; the deep flows live in §5).

- [ ] **Step 2: Add the Azure restatement note** — a short callout: "Cloud placement: the existing FieldJetX platform and all new infra run on Azure; the SQL Server system of record stays on AWS (sole cross-cloud dependency). This restates the existing-platform cloud from the per-use-case docs."

- [ ] **Step 3: Verify**

Run: `grep -i 'sole cross-cloud' stream1-unified-architecture.html`
Expected: one match.

Run: `open stream1-unified-architecture.html`
Expected: §1 shows the three-UC framing + Azure note.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add Stream 1 overview section"
```

---

### Task 3: Section 2a — Unified HLD diagram (Azure-transformed)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s2`)
- Read: `unified-hld.html`

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s2` containing sub-heading "2a · Unified system diagram" + the transformed SVG. Later task 4 appends 2b to the same section.

- [ ] **Step 1: Copy the `<svg viewBox="0 0 1200 1020">…</svg>`** from `unified-hld.html` (lines ~70–238) into `#s2` under an `<h3>2a · Unified system diagram</h3>`.

- [ ] **Step 2: Apply the cloud transform to the SVG label text** using the Global Constraints map. Concretely edit the zone/box/arrow `<text>` labels:
  - "NEW INFRASTRUCTURE · THIS PROJECT AWS" → "…Azure"
  - "EXISTING · FIELDJETX PLATFORM / AWS · unchanged" → "…Azure · restated"
  - "AWS EC2 · Application Host" → "Azure VM · Application Host"
  - "ECS Tasks / AWS ECS Fargate · workers" → "Container Apps / Azure Container Apps · workers"
  - "FastAPI AI Server / AWS ECS Fargate" → "…Azure Container Apps"
  - "Amazon SNS" → "Azure Notification Hubs"; "SNS Publish" → "Publish"; "APNs / FCM push" unchanged
  - "Redis Stream" → "Azure Cache for Redis"
  - "CloudWatch · logs" → "Azure Monitor · logs"
  - **Leave the SQL Server DB node as-is and add an `AWS` marker** on it (small badge/text `AWS` near "🗄️ SQL Server DB") — it is the one AWS component.

- [ ] **Step 3: Do NOT copy the `<script>` toggle** and do NOT copy the AWS/Azure toggle buttons. Single static Azure view.

- [ ] **Step 4: Add a one-line legend note** under the SVG: "All components Azure except the SQL Server system of record (AWS) — the single cross-cloud dependency."

- [ ] **Step 5: Verify**

Run: `grep -c 'Azure' stream1-unified-architecture.html`
Expected: ≥6 matches.

Run: `grep -c 'cloud-toggle' stream1-unified-architecture.html`
Expected: `0`.

Run: `open stream1-unified-architecture.html`
Expected: §2a renders the diagram; DB shows AWS, everything else Azure; no toggle.

- [ ] **Step 6: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add unified HLD diagram (Azure-transformed, DB on AWS)"
```

---

### Task 4: Section 2b — Three detailed HLDs (A, B, C), one by one

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s2`, appended after 2a)
- Read: `system-design.html`, `usecase-b-architecture.html`, `usecase-C-system-design.html`

**Interfaces:**
- Consumes: `#s2` with 2a already present; palette classes from Task 1.
- Produces: `#s2` sub-block "2b · Detailed architecture per use case" with three lifted+transformed diagrams in order A → B → C.

- [ ] **Step 1: Add `<h3>2b · Detailed architecture per use case</h3>`.**

- [ ] **Step 2: Lift Use Case A architecture diagram** — copy the `diagram-frame` HTML/CSS block from `system-design.html` (§4 High-Level Architecture). Copy its supporting CSS classes into the doc `<style>` if not already present. Apply the cloud transform to labels (EC2→Azure VM, ECS→Container Apps, Redis→Azure Cache for Redis, SNS→Azure Notification Hubs, SQL Server→keep + AWS badge). Precede with a one-line intro: "A adds: durable dispatch queue + Container Apps worker + push-offer cascade."

- [ ] **Step 3: Lift Use Case B architecture diagram** — copy the primary architecture `<svg>` from `usecase-b-architecture.html` (§6 High-Level Architecture; the first/largest SVG). Transform labels. Intro: "B adds: central FastAPI AI server + vector history index + summarise pipeline."

- [ ] **Step 4: Lift Use Case C architecture diagram** — copy the architecture `<svg>` from `usecase-C-system-design.html` (the single top SVG). Transform labels; reconcile "S3 Vectors" → "Azure-hosted vector store". Intro: "C adds: four-source part search + fuzzy matching + self-learning index."

- [ ] **Step 5: Verify**

Run: `grep -c '<svg' stream1-unified-architecture.html`
Expected: ≥3 (unified + B + C SVGs; A is HTML `diagram-frame`).

Run: `grep -c 'diagram-frame' stream1-unified-architecture.html`
Expected: ≥1 (A diagram).

Run: `open stream1-unified-architecture.html`
Expected: §2b shows three diagrams in order A, B, C; all Azure labels except SQL Server; no broken SVG.

- [ ] **Step 6: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add per-use-case detailed HLDs (A, B, C)"
```

---

### Task 5: Section 3 — Unified Technology Stack

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s3`)
- Read: §3 Technology Stack of `system-design.html` and `usecase-b-architecture.html`; stack refs in `usecase-C-system-design.html`

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s3` — one table, columns Layer | A | B | C, shared rows flagged.

- [ ] **Step 1: Build a unified stack table.** Rows: Client (Flutter mobile, Web console — shared), App/API host (.NET on Azure VM — shared), Central AI (FastAPI on Azure Container Apps — B,C), Workers (Azure Container Apps 0–1 — A), Queue (Azure Cache for Redis — A), Vector store (Azure-hosted — B,C), Push (Azure Notification Hubs — A), DB (**AWS SQL Server** — shared), Models (LiteLLM + qwen3-vl-moe + bge-m3 + Gemini fallback — B,C), Observability (OpenTelemetry + Azure Monitor — shared). Mark cells N/A where a UC doesn't use a layer.

- [ ] **Step 2: Apply cloud transform** to every AWS term pulled from source stack sections. DB row explicitly AWS.

- [ ] **Step 3: Verify**

Run: `grep -i 'AWS SQL Server' stream1-unified-architecture.html`
Expected: ≥1 match.

Run: `open stream1-unified-architecture.html`
Expected: §3 stack table renders with A/B/C columns.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add unified technology stack section"
```

---

### Task 6: Section 4 — Infrastructure + cross-cloud note

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s4`)
- Read: `unified-hld.html` (inventory + counts), §5/§8 Infrastructure of A and B

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s4` — Azure component inventory (the "What We Have vs What We Introduce" cards, transformed) + explicit cross-cloud subsection.

- [ ] **Step 1: Lift the `.inv` two-card inventory + `.counts`** from `unified-hld.html`. Apply cloud transform to every `<li>` and `.pill` (pills: `aws`→relabel "Azure", keep one AWS pill only on the SQL Server DB row).

- [ ] **Step 2: Add a "Cross-cloud dependency" callout** — Azure compute (Container Apps, VM) connects to AWS-hosted SQL Server. Note: network path (VPN/peering or public + TLS), added latency on every DB read/write, cross-cloud egress/data-transfer cost, and that this DB is the single seam between clouds. This is net-new content required by the spec.

- [ ] **Step 3: Verify**

Run: `grep -i 'cross-cloud dependency' stream1-unified-architecture.html`
Expected: one match.

Run: `open stream1-unified-architecture.html`
Expected: §4 shows Azure inventory + cross-cloud note; only DB pill says AWS.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add infrastructure section with cross-cloud note"
```

---

### Task 7: Section 5 — Operational Flows (A, B, C)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s5`)
- Read: §7 Operational Flows (A), §7 Operational Flows + §4/§5 user flows (B), Request flow (C)

**Interfaces:**
- Consumes: doc shell; flow-step/opsflow CSS (copy any missing classes into `<style>`).
- Produces: `#s5` with three labelled flow subsections.

- [ ] **Step 1: Lift A's operational flow** (dispatch board → rank → offer → accept/decline cascade → timeout escalate → assign) — copy the flow markup + SNS round-trip. Transform SNS→Azure Notification Hubs.

- [ ] **Step 2: Lift B's flows** — today-without-AI and with-AI-copilot flows + the summarise op flow. Keep both.

- [ ] **Step 3: Lift C's request flow** — four-source find (truck → nearby trucks → warehouse → supplier) → allocate. Transform any AWS labels.

- [ ] **Step 4: Verify**

Run: `open stream1-unified-architecture.html`
Expected: §5 shows three flow subsections A/B/C; step diagrams render; no AWS terms except DB.

Run: `grep -ci 'ECS\|Fargate\|CloudWatch\|Amazon SNS' stream1-unified-architecture.html`
Expected: `0` (all transformed).

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add operational flows for A, B, C"
```

---

### Task 8: Section 6 — Core Logic per use case (full fidelity)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s6`)
- Read: §8 Ranking Algorithm (A), §10 Summarise Pipeline + §12 Retrieval (B), Pipeline/Scoring/Indexing self-learning (C)

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s6` with three deep-dive subsections — no condensing.

- [ ] **Step 1: Lift A's ranking algorithm verbatim** — the weighted-sum formula, the four factors (distance/ETA, prior-visit familiarity, time-until-free, priority), per-branch configurable weights. Keep every formula and worked example.

- [ ] **Step 2: Lift B's summarise pipeline verbatim** — all pipeline stages + retrieval mechanics + the measured baseline figures. Keep tables.

- [ ] **Step 3: Lift C's matching logic verbatim** — pipeline, exact scoring, the self-learning indexing loop, source-tier ordering/allocation. Transform vector-store references to Azure-hosted.

- [ ] **Step 4: Verify**

Run: `grep -ci 'weight\|pipeline\|scoring' stream1-unified-architecture.html`
Expected: ≥3.

Run: `open stream1-unified-architecture.html`
Expected: §6 shows A ranking formula, B pipeline, C matching — full tables/formulas intact.

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add per-use-case core logic (ranking, summarise, matching)"
```

---

### Task 9: Section 7 — Data & Schema (A, B, C)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s7`)
- Read: §6 Redis Data Structures (A), §9 Data & ai.* Schema (B), System-of-record + Vector store (C)

**Interfaces:**
- Consumes: doc shell; ER-diagram CSS (copy missing classes).
- Produces: `#s7` with three data subsections.

- [ ] **Step 1: Lift A's Redis data structures** (streams, locks, lists) verbatim. Transform "Redis/ElastiCache" → "Azure Cache for Redis".

- [ ] **Step 2: Lift B's `ai.*` schema** — the ER diagram + table definitions, verbatim.

- [ ] **Step 3: Lift C's system-of-record + vector store** tables. Transform S3 Vectors → Azure-hosted vector store. Note SQL Server system-of-record stays AWS.

- [ ] **Step 4: Verify**

Run: `grep -i 'ai\.' stream1-unified-architecture.html | head -1`
Expected: `ai.*` schema references present.

Run: `open stream1-unified-architecture.html`
Expected: §7 shows Redis structures, ai.* ER diagram, C tables.

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add data and schema section (A/B/C)"
```

---

### Task 10: Section 8 — API Reference (A, B, C)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s8`)
- Read: §9 API Reference (A), §11 API Reference (B), supplier/API refs (C)

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s8` with three endpoint subsections, full parameter lists.

- [ ] **Step 1: Lift A's API reference** — all endpoints + params verbatim.

- [ ] **Step 2: Lift B's API reference** — all endpoints + params verbatim.

- [ ] **Step 3: Lift C's endpoints + supplier gateway contract** — verbatim, including the United CP Gateway contract notes.

- [ ] **Step 4: Verify**

Run: `open stream1-unified-architecture.html`
Expected: §8 shows three API subsections with full param tables.

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add API reference section (A/B/C)"
```

---

### Task 11: Section 9 — Observability & Evals

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s9`)
- Read: observability block in `unified-hld.html`, §13 Observability & Evals (B)

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s9`.

- [ ] **Step 1: Lift the unified observability block** — OpenTelemetry distributed tracing + logs. Transform CloudWatch → Azure Monitor.

- [ ] **Step 2: Lift B's evals section** verbatim — eval methodology, metrics, label-quality reality.

- [ ] **Step 3: Verify**

Run: `grep -i 'Azure Monitor\|OpenTelemetry' stream1-unified-architecture.html`
Expected: ≥1 each.

Run: `open stream1-unified-architecture.html`
Expected: §9 shows observability + evals.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add observability and evals section"
```

---

### Task 12: Section 10 — Cost Projection (Azure-priced)

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s10`)
- Read: §13 Cost Projection (A); any cost refs in B/C

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s10` — A|B|C cost line items, Azure service names.

- [ ] **Step 1: Lift A's cost line items** and relabel AWS services to Azure equivalents (EC2→Azure VM, ECS Fargate→Container Apps, ElastiCache→Azure Cache for Redis, SNS→Notification Hubs). Keep line-item granularity and figures; add a note that figures are the source AWS estimates pending Azure re-pricing.

- [ ] **Step 2: Add B and C cost rows** where source provides them; note the shared central AI server + vector store cost is shared across B and C. Keep the AWS SQL Server DB as its own line (only AWS cost + cross-cloud egress line).

- [ ] **Step 3: Verify**

Run: `open stream1-unified-architecture.html`
Expected: §10 cost table renders, Azure service names, DB line marked AWS + egress line present.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add cost projection section (Azure-priced)"
```

---

### Task 13: Section 11 — Onboarding & Fault Tolerance

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s11`)
- Read: §11 Onboarding + §12 Fault Tolerance (A), §14 Onboarding + §15 Fault Tolerance (B), C where applicable

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s11` with per-UC onboarding + fault-tolerance subsections.

- [ ] **Step 1: Lift A's onboarding plan + fault tolerance** verbatim; transform AWS terms.

- [ ] **Step 2: Lift B's onboarding + fault tolerance** verbatim.

- [ ] **Step 3: Add C fault-tolerance/onboarding** notes from its source (supplier-timeout fallback, self-learning cold start) if present; otherwise note "covered by shared central AI server resilience".

- [ ] **Step 4: Verify**

Run: `open stream1-unified-architecture.html`
Expected: §11 shows onboarding + fault tolerance per UC.

- [ ] **Step 5: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add onboarding and fault tolerance section"
```

---

### Task 14: Section 12 — Non-goals & PII

**Files:**
- Modify: `stream1-unified-architecture.html` (section `#s12`)
- Read: PII inventory (C), non-goals across A/B/C

**Interfaces:**
- Consumes: doc shell.
- Produces: `#s12`.

- [ ] **Step 1: Lift C's PII inventory** table verbatim.

- [ ] **Step 2: Consolidate non-goals** — A: not route optimization (911-style closest-available). B: never fabricates, never blocks Save; completeness over prose. C: no price ranking, no ordering; one supplier for POC. Plus the shared data note (16.3M notes, de-dup + PII strip before any model).

- [ ] **Step 3: Verify**

Run: `grep -i 'PII\|non-goal\|route optimization\|never fabricates' stream1-unified-architecture.html`
Expected: multiple matches.

Run: `open stream1-unified-architecture.html`
Expected: §12 shows PII inventory + consolidated non-goals.

- [ ] **Step 4: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Add non-goals and PII section"
```

---

### Task 15: Full-document review pass

**Files:**
- Modify: `stream1-unified-architecture.html` (fixes only)

**Interfaces:**
- Consumes: complete doc.
- Produces: verified final doc.

- [ ] **Step 1: Cloud-consistency sweep**

Run: `grep -nci 'AWS EC2\|ECS Fargate\|ECS Task\|Amazon SNS\|CloudWatch\|ElastiCache\|S3 Vectors' stream1-unified-architecture.html`
Expected: `0`. If non-zero, transform the stragglers.

- [ ] **Step 2: Confirm AWS appears ONLY for the database**

Run: `grep -ni 'AWS' stream1-unified-architecture.html`
Expected: every match is about SQL Server / the DB / cross-cloud egress. Fix any stray AWS references.

- [ ] **Step 3: Confirm no toggle leaked in**

Run: `grep -ci 'cloud-toggle\|data-cloud\|toAzure' stream1-unified-architecture.html`
Expected: `0`.

- [ ] **Step 4: Confirm HLD ordering** — open the file; verify §2 shows the unified diagram first, then A, then B, then C.

- [ ] **Step 5: Confirm self-contained** — no `src=`/`href=` to external hosts, no external `<link rel="stylesheet">`, no external `<script src>`.

Run: `grep -nE 'src="http|href="http|link rel="stylesheet"' stream1-unified-architecture.html`
Expected: no matches (or only in-page anchors).

- [ ] **Step 6: Full render check**

Run: `open stream1-unified-architecture.html`
Expected: all 12 sections + HLD render cleanly; no broken diagrams; horizontal scroll only inside diagram containers.

- [ ] **Step 7: Commit**

```bash
git add stream1-unified-architecture.html
git commit -m "Final review pass on Stream 1 unified architecture"
```

---

## Self-Review (plan author)

**Spec coverage:** Every spec outline section 1–12 maps to a task (T2, T3+T4, T5, T6, T7, T8, T9, T10, T11, T12, T13, T14). Cloud transform rules → Global Constraints + applied per task + T15 sweep. HLD unified-then-A/B/C order → T3 (2a) + T4 (2b). Full fidelity → T8/T9/T10 lift verbatim. Cross-cloud note → T6. Toggle dropped → T3 step 3 + T15 step 3. New-file, self-contained → T1 + T15 step 5.

**Placeholder scan:** No "TBD"/"implement later". Content steps name the exact source section to lift and the exact transform to apply.

**Consistency:** Section ids `#s1`–`#s12` consistent across tasks. Transform terminology identical to Global Constraints table everywhere.
