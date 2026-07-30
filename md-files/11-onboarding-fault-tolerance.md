<!--
  §11 Onboarding & Fault Tolerance — SOURCE OF TRUTH for this section.
  Edit here, then run: python3 scripts/build_docx.py

  `#` section title · `##` subsection (in Contents; bare `A `/`B `/`C `/`B C `
  prefix = coloured badge) · `###` sub-subsection · pipe tables get house
  style automatically · ``` fences ``` = mono box · `> quote` = copper callout.

  Rewritten for scanning: one shared four-phase rail, then only what differs per
  use case. Every fact from the long-form version is retained; the narrative
  walkthroughs (push-token cohorts, worker crash/slow reasoning) are compressed
  into callouts and failure tables.
-->

# 11. Onboarding & Fault Tolerance

Two questions per use case: how it gets from an empty production environment to live technician traffic, and how it behaves when something it depends on fails. The rollout shape is identical for all three — only the contents of each phase differ.

> **Deployment follows the existing FieldJetX development team's process.** Their pipelines, their staging → production promotion, their release windows, their rollback. Stream 1 adds no new deployment tooling: the dispatch worker image and the `.NET` proxy route ride the client's established pipeline on the shared EC2 host, and any client-owned code change is scheduled with their team rather than ours.

## How every rollout runs

| Phase | Purpose | Gate before the next phase |
| --- | --- | --- |
| **0 · Provision** | Stand up the infrastructure the feature cannot start without — network, hosting, queues, stores, credentials. | Every dependency reachable and health-checked |
| **1 · Seed** | Load the data the logic reads on its very first request: config, schema, indexes, history. | Nothing is empty at first call — no cold start |
| **2 · Roll out** | Ship the client experience behind a flag or app-version gate, to a pilot cohort only. | Pilot cohort live; everyone else unchanged |
| **3 · Go live** | Monitoring first, then one division/branch, then expand. | Pilot clean on its own metrics before widening |

Each environment is fully isolated — separate queues, databases, indexes and keys — so a staging run can never touch live technician or customer data.

## A Auto-Dispatch

### Onboarding

| Phase | What Auto-Dispatch needs | Cleared when |
| --- | --- | --- |
| **0 · Provision** | ElastiCache for Redis cluster up with the consumer group created (`XGROUP CREATE dispatch:stream`) — workers cannot read the stream before it exists. Worker image in ECR, ECS Fargate task definition, scale 0↔N policy. Amazon SNS platform applications for APNs (Apple `.p8`) and FCM. IAM: SNS publish, ECS scale control, ElastiCache access. | Workers consume the stream, and `/devices/register` has live push credentials behind it |
| **1 · Seed per division** | Ranking weights — distance, familiarity, priority, availability window — written into SQL Server. Toggle defaults **OFF** for every division. Escalation target (the human dispatcher queue) defined. Technician records carry division, location source and skills. | Config and an escalation target exist for every division; nothing auto-dispatches yet |
| **2 · Roll out push** | Push-enabled app build with a minimum-version gate. New technicians register at sign-up; existing ones register on first open of the updated build. The app re-registers on OS token rotation and a periodic refresh, upserting on (`techId`, `token`). | Push-adoption % climbing per division |
| **3 · Go live** | Monitoring first — push adoption, stream lag, lock-hold time, `BLPOP` timeout rate. Pilot one division, validate exactly-once assignment and escalation end to end, then expand division by division. | Pilot clean; manual fallback retired as adoption nears 100% |

> **The one cohort with a gap:** a technician who has not yet opened the push-enabled build has no installation id, so Amazon SNS cannot ring them. They are skipped to manual assignment — never offered a job they cannot receive — and rejoin automatically on their next token refresh. No migration job and no per-technician provisioning.

<!-- -->

> **New personal data:** the push token and its SNS `endpointArn` (`techId` → `endpointArn`) are the only new PII this project stores — encrypted at rest, limited to the dispatch backend, overwritten on rotation and cleaned up when dead. Technician location is read from the platform's existing system, not newly stored.

### Fault Tolerance

A dispatch is handed to exactly one worker, and the queue tracks it as *handed out but not finished* until that worker marks it done.

| Failure | Behaviour | Why it is safe |
| --- | --- | --- |
| Worker dies mid-dispatch | The request stays flagged unfinished; after the visibility timeout another worker claims and completes it | Nothing is lost — the request is recovered without an operator |
| Worker is slow, not dead | It still holds the per-technician claim, so the worker attempting takeover is blocked | No double offer — the same job never reaches two technicians |
| Worker truly crashed | Its claim releases automatically after a short hold, and a healthy worker takes over | The claim is the arbiter: still held means stay out, released means go ahead |
| No technician accepts | The 30-second offer window cascades down the shortlist, then escalates to a human dispatcher | A job is never silently dropped |

**Net effect — exactly-once:** every request is processed even if a worker dies, and no request is processed twice even if a worker is slow.

## B Job Summarisation

### Onboarding

| Phase | What the copilot needs | Cleared when |
| --- | --- | --- |
| **0 · Provision** | Private subnet and internal load balancer (idle timeout ≥ 120 s) — the AI service gets no public URL. FastAPI image in the registry, always-on at min 2 instances on Azure Container Apps (the shared service that also serves C). Network path and key for the client's private model gateway. Secrets — gateway key, internal proxy key, `FJX_API_TOKEN` — in Azure Key Vault, never in code or images. The `.NET` proxy route is client-owned code, so it is scheduled with their team. | AI service reachable privately; models answer; no secret outside the vault |
| **1 · Seed** | DBA sign-off on the read-only SQL Server account, then the AI MongoDB database and its collections (`summaries`, `llm_calls`, `summary_edits`) with indexes on Azure Cosmos DB for MongoDB. `ticket_standard.md` v1 agreed and frozen — every prompt and eval references a version. Co-occurrence tables seeded by one idempotent SQL aggregation over 12 months of dispatch/parts history. Pilot customers' compliance procedures verified current. | Schema, standard and history in place — gap checks have something to check against |
| **2 · Roll out** | Copilot build plus min-version gate for the pilot cohort. Older app versions keep today's manual review page and simply never call the AI route. Assignment trigger decided (poll vs `.NET` hook — open client item). Pilot cohort briefed: the AI drafts, they review, edit and submit. | Pilot branch live; every other branch unchanged |
| **3 · Go live** | Monitoring first — LLM latency and error rate, parse-failure rate, proxy timeout rate, edit-rate dashboard, all from `llm_calls` / `summary_edits`. Pilot one customer/branch on real dispatches, capture the edit-rate and call-back baseline, then expand branch by branch. | Baseline captured; any later prompt or model change passes the eval set first |

> **Editing is contributing, not correcting.** Technician edits feed the eval set (§9), so the pilot cohort is briefed that they stay accountable for the ticket — the copilot drafts, they sign off.

### Fault Tolerance

| Failure | Behaviour | Why it is safe |
| --- | --- | --- |
| An enrichment read fails | Pipeline continues without that block (fail-soft) | The ticket is built from what is available; missing context costs quality, not availability |
| Private gateway outage | AI features degrade to the manual experience — plain recap, briefings and suggestions skipped; submission never blocked | The gateway is the single model dependency and AI is an overlay, so losing it loses assistance, not function |
| Gateway saturated | Calls queue with a timeout; throughput drops from 30–35 tok/s single-call to ~11 tok/s at 4 concurrent, and calls past the timeout fall back to the manual recap | Latency degrades gracefully; the ~10% pilot keeps concurrency low and capacity is watched in `llm_calls` |
| Malformed model output | Parser falls back to regex extraction, then `MISSING` placeholders | The app always receives exactly 12 sections — a bad generation cannot break the review page |
| A Container Apps instance dies | The load balancer routes to the remaining instance and Container Apps replaces the replica | Minimum 2 always-on instances, so no cold-start window |
| AI tier unreachable | Review page falls back to today's manual recap; submission never blocked | Worst case is the pre-copilot experience |

**System of record:** AWS SQL Server stays the single source of truth. The AI tier writes only to its own MongoDB collections and never to SQL Server; job write-back rides the existing mobile-post path, so an AI failure cannot corrupt or block business data.

## C Parts Finder

### Onboarding

| Phase | What the parts finder needs | Cleared when |
| --- | --- | --- |
| **0 · Provision** | Azure Container Apps service on the private VNet with an internal load balancer, image built in CI. Azure-hosted vector store and index created; connectivity to the customer-hosted embedding model and LLM health-checked. Read-only path to AWS SQL Server plus connectivity to its own MongoDB, the `.NET` Legacy API and the United CP Gateway. MongoDB collections and indexes on Azure Cosmos DB; AI proxy route deployed on the same shared `.NET` route B uses. | All four sources and both models reachable |
| **1 · Seed the index** | Batch-embed historical completed dispatches on the self-hosted embedding model, idempotent upsert by `dispatchNo`. Validate retrieval quality on a held-out set of recent dispatches. | The index is never empty at go-live — the cold-start gap is closed from the platform's own history |
| **2 · Roll out** | Ship "Add Parts with AI" behind a feature flag, enabled per branch/division. Pilot a small technician cohort, watching acceptance rate and source mix (truck / warehouse / vendor, §6). | Flag on for the pilot cohort only |
| **3 · Go live** | Expand the flag division by division. Wire the on-completion re-embed pipeline so the index grows as dispatches close. | The self-learning loop runs without a separate retraining job |

### Fault Tolerance

| Failure | Behaviour | Why it is safe |
| --- | --- | --- |
| Models or vector store unavailable | `/parts/predict` returns `503`; the client falls back to manual inventory add | The flow continues — prediction is an accelerator, not a gate |
| Supplier (United) outage or timeout | That vendor tier is dropped from the part's sources; own-stock truck and warehouse options still return | The request does not fail — a United outage cannot block a technician who only needed own stock |
| Model throttling or slowness | Retry with backoff and batched pacing at index time; request-time timeouts bound prediction latency | Transient throttling cannot corrupt the index |
| Duplicate or repeated indexing | Idempotent upsert keyed by `dispatchNo` | Re-running indexing never double-counts a dispatch |
| SQL Server slow or unavailable | Read replicas plus brief caching for hot stock lookups; sourcing surfaces last-known availability where safe | Degrades to slightly stale stock rather than no answer |
| Container Apps replica crash | Stateless replicas behind the load balancer; Container Apps replaces unhealthy ones (health-checked via `/health`) | No single replica is load-bearing |

The vendor lookup is the only call in C that leaves the client's own infrastructure, which is why it is the one tier dropped independently rather than failing the whole `/parts/source` request.

## Environments

| Use case | Isolated per environment | Shared |
| --- | --- | --- |
| A Auto-Dispatch | Own ElastiCache for Redis, own SQL Server database, own ECS Fargate service | Existing EC2 application host |
| B Job Summarisation | Own Container Apps service, own MongoDB database | Private model gateway, `.NET` proxy route |
| C Parts Finder | Own vector index, supplier gateway on a test key in staging and a production key in production | Container Apps service and AI proxy route shared with B |
