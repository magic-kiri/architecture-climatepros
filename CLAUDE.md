# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is **not an application** — there is no build, no framework, no test suite, no `package.json`. It is a set of **standalone, self-contained HTML architecture/design documents** for ClimatePros (a.k.a. FieldJetX), a commercial refrigeration & HVAC field-service platform (~900–1,000 technicians, 46 branches, 10,000+ sites). Each HTML file inlines all its own CSS in a `<style>` block and is opened directly in a browser or served as a static page.

Everything documents the same product: automating three manual bottlenecks in a field-service job. Understanding a change usually means reading the problem statement plus one use-case design doc.

## Layout & how the documents relate

- `problem-statement.html` — the source of truth for *why*. Defines Use Cases A, B, C, their bottlenecks, and the shared messy-data context (16.3M note records, ~40% ≤40 chars). Read this first before touching any design doc.
- `system-design.html` — **Use Case A · Auto-Dispatch** (deterministic ranking algorithm, *no LLM* — must stay explainable). `index.html` is a meta-refresh redirect to this file (the GitHub Pages landing page). `overview.html`, `frag-architecture.html`, `frag-flows.html` are older/companion fragments for A.
- `usecase-b-architecture.html` — **Use Case B · Job Summarisation Copilot** (AI, technician overrides; RAG over historical jobs).
- `usecase-C-system-design.html` — **Use Case C · Technician Parts Finder** (AI, technician overrides; fuzzy part-number matching via vector search + supplier gateway). Note the capital `C` in the filename.
- `unified-hld.html` — the original cross-cutting High-Level Design tying A/B/C together, with an AWS/Azure cloud toggle. Superseded as a deliverable by `stream1-unified-architecture.html` (below) but still the source for that doc's unified diagram.
- `stream1-unified-architecture.html` — **the current primary deliverable**: the full "Stream 1" architecture merging A/B/C into one doc. This is NOT a standalone file — it is a thin runtime loader that renders fragments from `sections/`. See its dedicated section below.
- `spec-review-2026-07-03-132209.{md,json,html}` — a TL-agent review of Use Case A. The `.md` is authoritative; `.json` is its structured form; `.html` is the rendered view. Treat these as a snapshot artifact, not a live doc.
- `use case b&c/` — a nested folder with an alternate Parts-Finder draft.

Use Cases A/B/C are also referred to by domain names: **Dispatch (A)**, **Closeout/Summarisation (B)**, **Parts (C)**.

## Stream 1 unified architecture (`stream1-unified-architecture.html`)

The merged full architecture for all three use cases. **Built as a runtime loader + fragments, NOT one hand-edited file.**

**How it is assembled**
- `stream1-unified-architecture.html` — a ~50-line shell. It `fetch()`es each fragment listed in its `PARTS`/`NAV`/`BODY` arrays and injects them into the DOM in order, then re-executes injected `<script>` (needed for the sidebar scrollspy). **You rarely edit this file** — only to add/remove/reorder a section in its arrays.
- `sections/` holds every editable piece:
  - `style.css` — shared stylesheet (linked via `<link>`; holds the `:root` palette + shared component classes + the nav-sidebar rules)
  - `_nav.html` — the fixed left navigation sidebar + its scrollspy `<script>`
  - `_hero.html` — the page hero header
  - `01.html` … `12.html` — one `<section id="sN">…</section>` per concern (see map below)

**Section map (concern-first; each concern has A/B/C subsections inside)**
1 Overview · 2 High-Level Architecture (2a unified diagram, then 2b A→B→C detailed diagrams) · 3 Technology Stack · 4 Infrastructure · 5 Operational Flows · 6 Core Logic · 7 Data & Schema · 8 API Reference · 9 Observability & Evals · 10 Cost Projection · 11 Onboarding & Fault Tolerance · 12 Non-goals & PII. So `#sN` ⇄ `sections/NN.html`.

**Editing rules**
- Edit the fragment (`sections/NN.html`), then **refresh the browser — there is no build step for the live doc**.
- Put section-specific CSS in a `<style>` block at the top of the fragment, class-names **namespaced `sN-*`** (e.g. `s7-er-*`) so they never collide across fragments; keep `style.css` for shared/base rules only.
- Adding a new section = create the fragment + add its id to the shell's `BODY` array + add a nav `<a href="#sN">` in `_nav.html`.
- Cross-references between sections use plain text `§N` (no anchors needed for prose); verify the target number when you move content.

**Serving / deployment**
- Must be served over **http** — `fetch()` is blocked on `file://`. Locally: `python3 -m http.server` then open `http://localhost:8000/stream1-unified-architecture.html`.
- **GitHub Pages works** (https). `.nojekyll` is committed at the repo root **because Jekyll skips underscore-prefixed files** — without it `_nav.html`/`_hero.html` would 404. Do not delete `.nojekyll`.
- `scripts/build.py` is an **optional bundler**: it inlines everything into a single self-contained `stream1-unified-architecture.bundle.html` (opens via `file://` / double-click). The bundle is gitignored; regenerate on demand. Editing the bundle directly is pointless — edit fragments and rebuild.

**Cloud model — differs from the source A/B/C docs, keep it exact**
- Everything runs on **Azure EXCEPT the SQL Server database, which stays on AWS** — the single cross-cloud dependency. The AWS/Azure toggle from `unified-hld.html` is **dropped**; this doc commits to Azure.
- Transform map applied throughout: EC2→**Azure VM**, ECS Fargate→**Azure Container Apps**, Redis/ElastiCache→**Azure Cache for Redis**, SNS→**Azure Notification Hubs**, CloudWatch→**Azure Monitor**, S3 Vectors→**Azure-hosted vector store**. Model layer stays on-prem (LiteLLM + self-hosted qwen3-vl-moe/vLLM + bge-m3 embedding + Gemini fallback).
- Any "AWS" text in this doc must refer to ONLY: the SQL Server DB, the cross-cloud seam (VPC peering / egress), or explicit "source-was-AWS → now Azure" provenance (e.g. cost/PII notes). A live component labelled AWS other than the DB is a bug.
- Content is **full-fidelity** — formulas (A ranking), schemas (B `ai.*`), scoring (C), API params, and cost line items are lifted verbatim from the source A/B/C docs; don't summarise them away.

**Design/plan artifacts:** `docs/superpowers/specs/2026-07-17-stream1-unified-architecture-design.md` (spec) and `docs/superpowers/plans/2026-07-17-stream1-unified-architecture.md` (task plan) record the decisions behind this doc.

## Architecture facts to keep consistent

These recur across the docs; when editing one, keep them aligned with the others:

- **A is a deterministic weighted-sum ranking — no LLM.** It ranks technicians on four factors (distance/ETA, prior-visit familiarity, time-until-free, job priority), pushes accept/decline offers that cascade on timeout, weights configurable per branch. Do not describe it as AI. It is *closest-available-responder* (911-style), **not route optimization**.
- **B and C are AI, and the technician can always override.** B never fabricates and never blocks Save; its headline value is *completeness*, not prose. C shows part + location + distance and stops there — it does **not** rank by price or order anything.
- **Shared stack** across docs: Flutter mobile app · FastAPI services · SQL Server on Amazon RDS (system of record) · AWS ECS Fargate workers. A adds Redis/ElastiCache (Streams, locks, lists) + SNS → APNs/FCM push. B and C add embeddings + vector search (S3 Vectors) with a self-host option. **Cloud caveat:** the source docs (`system-design.html`, `usecase-*.html`, `unified-hld.html`) are AWS-based (unified-hld has an AWS⇄Azure toggle). The merged `stream1-unified-architecture.html` is **Azure-only except the AWS SQL Server DB** — do not conflate the two; use the source docs' AWS terms only when editing the source docs.
- **Savings targets:** only B claims a before/after (**10–15 min → ~15 s**). A and C have measured baselines but no agreed target — don't invent one.

## Working in this repo

- **No test runner; two doc styles.** The **source docs** (`system-design.html`, `usecase-*.html`, `problem-statement.html`, `unified-hld.html`, …) are standalone self-contained files — preview with `open <file>.html`, keep them self-contained (no external CSS/deps). The **unified doc** (`stream1-unified-architecture.html`) is the loader+fragments model above — preview by serving over http (`python3 -m http.server`), edit `sections/NN.html`, refresh.
- **Edits are hand-authored HTML+CSS.** Match the file's existing structure: numbered `<h2>` sections, the shared CSS-variable palette in `:root` (`--blue`/`--amber`/`--green`/`--red` soft/line pairs), chip/card/flow-step class conventions.
- **Deployment is GitHub Pages** (remote `magic-kiri/architecture-climatepros`). The site root resolves through `index.html` → `system-design.html`; to make the unified doc the landing page, repoint that redirect. Keep `.nojekyll` (required for the unified doc's `_`-prefixed fragments to serve).
- Commit only when asked. Design content is the deliverable — verify factual consistency against `problem-statement.html` before committing wording changes.
