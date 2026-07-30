#!/usr/bin/env python3
"""Assemble sections/*.html -> one Google-Docs-ready HTML document.

Cloud rule applied (confirmed by client): anything AI-specific runs on Azure;
everything else runs on AWS. Stale Azure-first terminology in sections 5,7-12 is
normalised; every replacement is asserted so nothing fails silently.
"""
import re, sys, pathlib, markdown

SRC = pathlib.Path('/tmp/x')
OUT = pathlib.Path(__file__).parent

FIX_LOG = []

def norm(s):
    """Normalise curly punctuation so match strings don't hinge on quote style."""
    return s.replace('’', "'").replace('‘', "'")

def sub(text, old, new, count, label):
    text, old = norm(text), norm(old)
    n = text.count(old)
    if n != count:
        raise SystemExit(f'REPLACE MISS [{label}]: expected {count} got {n}\n  {old[:120]!r}')
    FIX_LOG.append((label, old, new, n))
    return text.replace(old, new)

# ---------------------------------------------------------------- global terms
GLOBAL = [
    ('Azure VM', 'AWS EC2'),
    ('Azure Notification Hubs', 'Amazon SNS'),
    ('Notification Hubs', 'Amazon SNS'),
    ('Azure Cache for Redis', 'Amazon ElastiCache for Redis'),
    ('deviceInstallationId', 'endpointArn'),
    ('device installation id', 'platform endpoint ARN'),
    ('ai.summary_edits', 'the summary_edits collection'),
    ('ai.summaries', 'the summaries collection'),
    ('ai.llm_calls', 'the llm_calls collection'),
    ('ai.* tables', 'the AI MongoDB collections'),
]

def load(name):
    t = (SRC / f'{name}.md').read_text()
    t = re.sub(r'^\s*@@@@ FILE:.*$', '', t, flags=re.M).strip() + '\n'
    return norm(t)

S = {n: load(n) for n in
     ['01','02','03','04','05','06','07','08','09','10','11','12']}

# ------------------------------------------------- global term pass (runs first)
for name in S:
    for old, new in GLOBAL:
        if old in S[name]:
            n = S[name].count(old)
            S[name] = S[name].replace(old, new)
            FIX_LOG.append((f'S{int(name)} · global term', old, new, n))

# ---------------------------------------------------------------- section 2
S['02'] = sub(S['02'],
    'AWS SQL Server is the sole AWS component; .NET Legacy/Microservices API, Container Apps, Redis and Amazon SNS all run on Azure .',
    'All of Use Case A runs on AWS: the .NET Legacy and Microservices APIs on AWS EC2, the dispatch workers on AWS ECS Fargate, '
    'the durable queue on Amazon ElastiCache for Redis, push through Amazon SNS, and AWS SQL Server as the system of record. '
    'No part of A touches Azure — there is no LLM in this use case.',
    1, 'S2 · 2b Use Case A caption — cloud placement corrected')

S['02'] = sub(S['02'],
    'the existing platform is restated on AWS EC2 — no AWS-specific managed service appears in this diagram.',
    'the existing platform is restated on AWS EC2. The FastAPI AI server and its datastores are the only Azure components in this diagram.',
    1, 'S2 · 2b B&C caption — stale "no AWS managed service" claim removed')

S['02'] = sub(S['02'],
    'AI data is self-contained. The FastAPI AI server owns its own ai.* schemas on the shared SQL Server and does not depend '
    'on the existing application tables — it persists its own outputs (summaries, part-search results) in its own schema. '
    "Because the AI datastore isn't coupled to the legacy relational schema, it could optionally migrate to a document store "
    '(e.g. MongoDB) later with little rework.',
    'AI data is self-contained. The FastAPI AI server owns its own MongoDB (Azure Cosmos DB for MongoDB, vCore) and holds no '
    'SQL Server connection at all — it persists its own outputs (summaries, part-search results, LLM-call traces and eval data) '
    'in its own collections. Any business context it needs arrives in the request payload from the .NET AI proxy, so the AI '
    'datastore is never coupled to the legacy relational schema.',
    1, 'S2 · AI datastore — ai.* on SQL Server → MongoDB on Azure')

# ---------------------------------------------------------------- section 5
S['05'] = sub(S['05'],
    '\U0001F4E6 Azure Container Apps pool picks up the dispatch',
    '\U0001F4E6 AWS ECS Fargate pool picks up the dispatch',
    1, 'S5 · A step 1 — dispatch workers are ECS Fargate, not Container Apps')

S['05'] = sub(S['05'],
    "The winning Container Apps worker calls Amazon SNS Send with the technician's platform endpoint ARN",
    "The winning ECS Fargate worker calls the Amazon SNS Publish API with the technician's platform endpoint ARN",
    1, 'S5 · push round-trip step 1 — SNS Publish, ECS Fargate worker')

S['05'] = sub(S['05'],
    'Amazon SNS fans the message out through APNs',
    'Amazon SNS fans the message out to the platform application endpoint through APNs',
    1, 'S5 · push round-trip step 2 — SNS platform application wording')

# ---------------------------------------------------------------- section 7
S['07'] = sub(S['07'],
    'B and C each persist AI output into their own isolated ai.* schema inside the shared AWS SQL Server , zero mixing with '
    'business tables ( \u00a73 ).',
    'B and C each persist AI output into the AI server\u2019s own MongoDB on Azure (Azure Cosmos DB for MongoDB, vCore) \u2014 a '
    'separate datastore from the AWS SQL Server system of record, with zero coupling to the business tables ( \u00a73 ).',
    1, 'S7 · intro — AI output store is MongoDB, not an ai.* SQL schema')

S['07'] = sub(S['07'],
    '### A Auto-Dispatch \u2014 Amazon ElastiCache for Redis Data Structures\n\nThe three Redis structures that coordinate '
    'dispatch across the Container Apps worker pool.',
    '### A Auto-Dispatch \u2014 Amazon ElastiCache for Redis Data Structures\n\nThe three Redis structures that coordinate '
    'dispatch across the ECS Fargate worker pool.',
    1, 'S7 · A heading body — Container Apps pool → ECS Fargate pool')

S['07'] = sub(S['07'],
    'between .NET Legacy API and the Container Apps workers',
    'between the .NET Legacy API on AWS EC2 and the ECS Fargate workers',
    1, 'S7 · STREAM row — producer/consumer are EC2 and ECS Fargate')

OLD_B = S['07'][S['07'].index('### B Job Summarisation'):S['07'].index('### C Parts Finder')]
NEW_B = '''### B Job Summarisation \u2014 the AI MongoDB Collections

All AI output lives in the AI server\u2019s own MongoDB (Azure Cosmos DB for MongoDB, vCore): a datastore owned entirely by the
FastAPI AI service, with no connection to the AWS SQL Server system of record and therefore zero mixing with business tables.
Indicative document shapes below; final collection and index design is agreed with the client DBA.

**summaries**

| Field | Type / notes |
|---|---|
| _id | ObjectId \u00b7 primary key |
| dispatchId | int \u00b7 reference to the SQL Server dispatch, carried in the request payload \u2014 not a database foreign key |
| sections | array \u00b7 the 12 sections |
| procedureResults | array |
| status | draft / accepted |
| acceptedAt | date |
| embedding | array&lt;double&gt; \u00b7 optional, stage 1 |

**llm_calls**

| Field | Type / notes |
|---|---|
| _id | ObjectId \u00b7 primary key |
| dispatchId | int |
| provider / model | gateway \u00b7 qwen3-vl |
| tokensIn / tokensOut | int |
| latencyMs | int |
| outcome | ok / parse_fail / error |

**summary_edits**

| Field | Type / notes |
|---|---|
| _id | ObjectId \u00b7 primary key |
| summaryId | reference \u2192 summaries._id |
| section | which of the 12 |
| beforeText / afterText | the correction |
| editedBy / editedAt | who \u00b7 when |

About the embedding field: it is a placeholder for the optional future vector layer ( \u00a76 ). Because MongoDB stores it as a
native array of doubles, the SQL Server 2022 Web Edition constraint that previously forced a varbinary column no longer
applies. It stays empty unless that layer is added. Open client items: collection and index design sign-off, and the
dispatch-assignment trigger mechanism.

'''
S['07'] = sub(S['07'], OLD_B, NEW_B, 1,
              'S7 \u00b7 B \u2014 relational ai.* schema rewritten as MongoDB collections')

S['07'] = sub(S['07'],
    'the vector store \u2014 an Azure-hosted vector store \u2014 holds the semantic index used for prediction. AI-written data '
    'lands in a new ai.* schema in the same SQL Server \u2014 clear isolation from the existing tables.',
    'the vector store \u2014 an Azure-hosted vector store \u2014 holds the semantic index used for prediction. AI-written data '
    'lands in the AI server\u2019s own MongoDB collections on Azure; the AI service performs no writes against SQL Server at all.',
    1, 'S7 · C intro — AI writes go to MongoDB, not a SQL ai.* schema')

S['07'] = sub(S['07'],
    '#### New ai.* schema \u2014 AI-owned relational data\n\nEverything the AI layer writes to SQL Server lives in its own '
    'schema: the parts lists a technician commits (with per-source allocations), prediction acceptance signals, and indexing '
    'bookkeeping. Nothing in the existing dbo tables changes \u2014 the AI footprint can be audited, backed up, or dropped '
    'independently.',
    '#### AI-owned collections \u2014 MongoDB Azure\n\nEverything the AI layer writes lives in its own MongoDB collections: the '
    'parts lists a technician commits (with per-source allocations), prediction acceptance signals, and indexing bookkeeping. '
    'Nothing in the existing SQL Server dbo tables changes and the AI service needs no write access to the system of record \u2014 '
    'the AI footprint can be audited, backed up, or dropped independently.\n\nLearning-loop mechanism: because the AI server has '
    'no SQL Server connection, dispatch completion cannot be observed by polling the database. The completed dispatch \u2014 its '
    'reason text and the parts actually used \u2014 is handed to the AI server by the .NET side through the AI-proxy route, which '
    'is what triggers the embed-and-upsert described in \u00a76. Confirming that trigger is an open client item.',
    1, 'S7 · C — ai.* schema section rewritten as MongoDB + learning-loop trigger stated')

# ---------------------------------------------------------------- section 9
S['09'] = sub(S['09'],
    '### Unified Observability \u2014 OpenTelemetry Tracing + Azure Monitor Logs',
    '### Unified Observability \u2014 OpenTelemetry Tracing + CloudWatch / Azure Monitor Logs',
    1, 'S9 · heading — both clouds\u2019 log sinks named')

S['09'] = sub(S['09'],
    'Every service in the new AI tier \u2014 the AWS EC2 host running both .NET APIs, both Azure Container Apps pools '
    '(Auto-Dispatch workers and the FastAPI AI server), the Redis-fed worker loop, and every vector-store call \u2014 emits '
    'OpenTelemetry traces and structured logs into a single Azure Monitor workspace ( \u00a73 , \u00a74 ).',
    'Every service in Stream 1 \u2014 the AWS EC2 host running both .NET APIs, the AWS ECS Fargate dispatch-worker pool (A), the '
    'Azure Container Apps FastAPI AI server (B, C), the Redis-fed worker loop, and every vector-store call \u2014 emits '
    'OpenTelemetry traces and structured logs. AWS-side services report into CloudWatch; the Azure AI stack reports into an '
    'Azure Monitor workspace, and trace context is propagated across the single AWS\u2192Azure hop so one dispatch is one trace '
    '( \u00a73 , \u00a74 ).',
    1, 'S9 · scope sentence — A is not an AI tier; split CloudWatch / Azure Monitor')

# ---------------------------------------------------------------- section 10
S['10'] = sub(S['10'],
    'Every dollar figure below is lifted as-is from its source design\u2019s AWS cost projection \u2014 only the service names are '
    'relabeled to their \u00a73 Technology Stack Azure equivalents (Fargate \u2192 Azure Container Apps, ElastiCache \u2192 Amazon '
    'ElastiCache for Redis, SNS \u2192 Amazon SNS, CloudWatch \u2192 Azure Monitor, EC2 \u2192 AWS EC2). No new Azure prices are '
    'estimated here: Container Apps\u2019 consumption pricing, Amazon ElastiCache for Redis tiers, and Amazon SNS\u2019 push pricing '
    'all differ from their AWS counterparts\u2019 rate cards, and none of the three source designs were re-priced against Azure. '
    'Treat every figure as directional, pending a real Azure re-pricing pass before this becomes a budget commitment.',
    'Every dollar figure below is lifted as-is from its source design\u2019s AWS cost projection. Under the confirmed cloud '
    'placement ( \u00a72 \u2013 \u00a74 ) Use Case A stays entirely on AWS \u2014 ECS Fargate, ElastiCache for Redis, SNS, CloudWatch '
    '\u2014 so those source rates apply to the services actually being bought and need no translation. The only lines that still '
    'require a re-pricing pass are the Azure-side AI components: Container Apps for the FastAPI AI server, the Azure-hosted '
    'vector store, and Azure Monitor for the AI stack.',
    1, 'S10 · intro — Azure relabelling premise removed; A prices as AWS')

S['10'] = sub(S['10'],
    'Pending Azure re-pricing: the numbers in this section are the original AWS estimates for A and C, carried over unchanged. '
    'Treat them as a same-order-of-magnitude placeholder, not a quote \u2014 get actual Azure Container Apps / Amazon ElastiCache '
    'for Redis / Amazon SNS / Azure Monitor rates before this section is used for a real budget.',
    'Pending re-pricing \u2014 Azure AI lines only: Use Case A\u2019s figures are AWS list rates for the services in the design, so '
    'they stand as directional AWS estimates. The shared B\u00b7C lines were sourced from AWS equivalents (Fargate, S3 Vectors, '
    'CloudWatch) and must be re-priced against Azure Container Apps, the chosen Azure vector store, and Azure Monitor before '
    'this section is used for a real budget.',
    1, 'S10 · callout — re-pricing scoped to the Azure AI lines')

S['10'] = sub(S['10'],
    'Only the Container Apps worker pool is a variable cost',
    'Only the ECS Fargate worker pool is a variable cost',
    1, 'S10 · A — variable cost is the Fargate pool')

S['10'] = sub(S['10'],
    'Source rates were us-east-1 AWS Fargate/ElastiCache/SNS list prices \u2014 verify against actual Azure rates at build time .',
    'Source rates are us-east-1 AWS Fargate / ElastiCache / SNS list prices \u2014 the services actually used; verify against '
    'current AWS rate cards at build time .',
    1, 'S10 · A — rate provenance now matches the services bought')

S['10'] = sub(S['10'],
    '#### Azure Container Apps cost formula \u2014 carried from the source Fargate formula',
    '#### AWS ECS Fargate cost formula',
    1, 'S10 · heading — Fargate formula is the live formula')

S['10'] = sub(S['10'],
    'Task = 1 vCPU / 2 GB \u2192 $0.04937 per task-hour (source AWS Fargate rate)',
    'Task = 1 vCPU / 2 GB \u2192 $0.04937 per task-hour (AWS Fargate rate). Note: \u00a74 Compute sizing states a 0.5 vCPU / 1 GB '
    'baseline for these workers \u2014 the two figures need to be reconciled before this is used for budget.',
    1, 'S10 · Fargate task rate — flagged sizing conflict with §4')

S['10'] = sub(S['10'],
    '#### Amazon ElastiCache for Redis + Amazon SNS cost \u2014 fixed & near-zero',
    '#### Amazon ElastiCache for Redis + Amazon SNS cost \u2014 fixed & near-zero',
    1, 'S10 · heading — already normalised by global pass')

S['10'] = sub(S['10'],
    'azure_cache = $0.032/hr x 730 hr/mo  =  ~$23.36/mo   (t4g.small-equivalent tier, always on)',
    'elasticache = $0.032/hr x 730 hr/mo  =  ~$23.36/mo   (cache.t4g.small, always on)',
    1, 'S10 · code — ElastiCache line and real instance class')

S['10'] = sub(S['10'],
    'notification_hubs = $0.50 per 1,000,000 pushes   (first 1M/mo free \u2014 source SNS rate)',
    'sns_push = $0.50 per 1,000,000 pushes   (first 1M/mo free \u2014 SNS mobile push rate)',
    1, 'S10 · code — SNS push line')

S['10'] = sub(S['10'],
    '| Scenario | N tasks | Hours ON/day | Container Apps/mo | Azure Cache/mo | Amazon SNS/push | Total/mo* |',
    '| Scenario | N tasks | Hours ON/day | ECS Fargate/mo | ElastiCache/mo | SNS/push | Total/mo* |',
    1, 'S10 · scenario table header — AWS service names')

S['10'] = sub(S['10'],
    '*Figures are the source AWS estimates carried over unrepriced (see callout above); excludes the existing AWS EC2 app host '
    '+ AWS SQL Server (sunk \u2014 unchanged by this project, itemized separately below). Azure Cache row uses the source\u2019s '
    'cache.t4g.small -equivalent fixed rate, ~$0.032/hr.',
    '*Figures are AWS list-rate estimates for the services in the design; excludes the existing AWS EC2 app host + AWS SQL '
    'Server (sunk \u2014 unchanged by this project, itemized separately below). ElastiCache row uses cache.t4g.small at '
    '~$0.032/hr.',
    1, 'S10 · table footnote — provenance and cache instance class')

S['10'] = sub(S['10'],
    'a disabled division drops its Container Apps line to $0',
    'a disabled division drops its ECS Fargate line to $0',
    1, 'S10 · scale-to-zero note — Fargate')

S['10'] = sub(S['10'],
    'Fixed floor stays ~$23/mo (Azure Cache) regardless.',
    'Fixed floor stays ~$23/mo (ElastiCache) regardless.',
    1, 'S10 · scale-to-zero note — ElastiCache floor')

S['10'] = sub(S['10'],
    'source rate: Amazon S3 Vectors',
    'source rate: Amazon S3 Vectors \u2014 needs Azure re-pricing',
    1, 'S10 · vector store line — flagged for Azure re-pricing')

# ---------------------------------------------------------------- section 11
S['11'] = sub(S['11'],
    '- Azure Container Apps ready: worker image pushed to the registry, container app definition (1 vCPU / 2 GB), sca',
    '- AWS ECS Fargate ready: worker image pushed to Amazon ECR, task definition (1 vCPU / 2 GB \u2014 reconcile with \u00a74\u2019s '
    '0.5 vCPU / 1 GB baseline), sca',
    1, 'S11 · A Phase 0 — ECS Fargate + ECR, sizing conflict flagged')

S['11'] = sub(S['11'],
    '- Azure RBAC roles : Amazon SNS Send, Container Apps scale control, Cache for Redis access.',
    '- AWS IAM roles : SNS Publish, ECS task scale control, ElastiCache access.',
    1, 'S11 · A Phase 0 — IAM instead of Azure RBAC')

S['11'] = sub(S['11'],
    'separate Amazon ElastiCache for Redis, isolated SQL Server database, separate Container Apps service',
    'separate Amazon ElastiCache for Redis, isolated SQL Server database, separate ECS Fargate service',
    1, 'S11 · A environments — per-env Fargate service')

# ------------------------------------- second pass: remaining ai.* / A-worker refs
S['02'] = sub(S['02'],
    'A adds: durable dispatch queue + Container Apps worker + push-offer cascade.',
    'A adds: durable dispatch queue + ECS Fargate worker + push-offer cascade.',
    1, 'S2 · 2b A summary line — ECS Fargate worker')

S['03'] = sub(S['03'],
    'B and C each add an isolated ai.* schema — zero mixing with business tables.',
    "B and C add no tables to SQL Server at all: they persist their AI output to the AI server's own MongoDB on Azure, "
    'and read business context only via the payload the .NET AI proxy sends.',
    1, 'S3 · Database row — AI output goes to MongoDB, not a SQL ai.* schema')

S['05'] = sub(S['05'],
    'division locks, Container Apps task walkthroughs',
    'division locks, ECS Fargate task walkthroughs',
    1, 'S5 · intro — ECS Fargate task walkthroughs')

S['05'] = sub(S['05'],
    'cached in ai.*',
    'cached in MongoDB',
    1, 'S5 · briefing builder — cached in MongoDB')

S['08'] = sub(S['08'],
    'parse failures, read from ai.* .',
    'parse failures, read from the AI MongoDB collections .',
    1, 'S8 · /admin/dashboard — reads MongoDB collections')

S['08'] = sub(S['08'],
    'scale the Container Apps pool up',
    'scale the ECS Fargate pool up',
    1, 'S8 · /divisions/{id}/toggle — scales the ECS Fargate pool')

S['09'] = sub(S['09'],
    'reads straight from the ai.* schema',
    'reads straight from the AI MongoDB collections',
    1, 'S9 · dashboard — reads MongoDB collections')

S['10'] = sub(S['10'],
    'N = number of Container Apps tasks',
    'N = number of ECS Fargate tasks',
    1, 'S10 · formula legend — ECS Fargate tasks')

S['10'] = sub(S['10'],
    '### Database & Cross-Cloud Egress — the One AWS Line\n\nPer §3 / §4 , the SQL Server system of record is the one piece '
    'of Stream 1 that deliberately stays on AWS instead of moving to Azure. It is its own cost line, not folded into the '
    'Azure figures above.',
    '### Database & Cross-Cloud Egress\n\nPer §3 / §4 , the SQL Server system of record stays on AWS and is read and written '
    'only by AWS-side compute (EC2 and ECS Fargate), so it carries no cross-cloud cost of its own. The single cross-cloud '
    'line is the AI request itself — the .NET AI-proxy call from AWS out to the FastAPI AI server on Azure. Both are their '
    'own cost lines, not folded into the figures above.',
    1, 'S10 · egress heading & intro — the seam is the AI request, not the database')

S['10'] = sub(S['10'],
    '| AWS SQL Server (system of record) | AWS | Existing / sunk — excluded from the A and C projections as unchanged by this '
    'project. No incremental cost here. |\n| Cross-cloud egress (Azure ↔ AWS data transfer) | AWS egress | TBD — depends on '
    'traffic. No source figure exists for this line in any of the three designs; see §4 Infrastructure. |',
    '| AWS SQL Server (system of record) | AWS | Existing / sunk — excluded from the A and C projections as unchanged by this '
    'project. No incremental cost, and no egress: only AWS-side compute connects to it. |\n'
    '| Cross-cloud egress (AWS → Azure AI requests) | AWS egress | TBD — depends on B/C volume. One request/response pair per '
    'summarisation or parts search, not a per-row transfer cost. No source figure exists for this line in any of the three '
    'designs; see §4 Infrastructure. |',
    1, 'S10 · egress table — rows rescoped to the AI-request hop')

S['10'] = sub(S['10'],
    "Every dispatch read/write (A) and every ai.* read/write (B, C) against AWS SQL Server from Azure compute bills AWS egress "
    "on the way out, per §4 's cross-cloud callout. Sizing this requires a traffic estimate (dispatches/day × summaries/day × "
    "parts-lookups/day × average payload size) that no source design provides",
    "Under the confirmed placement it is a narrow line: Use Case A never leaves AWS, and the AI server holds no SQL Server "
    "connection, so the only billable crossing is the .NET proxy's outbound AI request and its response (B, C), per §4 's "
    "cross-cloud callout. Sizing this requires a traffic estimate (summaries/day × parts-lookups/day × average payload size) "
    "that no source design provides",
    1, 'S10 · egress note — A stays in AWS; only B/C requests cross')

S['11'] = sub(S['11'],
    '- DBA approval, then create the ai.* schema on AWS SQL Server: the isolated namespace for summaries, call logs, and '
    'edits. Hard precondition for everything downstream.',
    '- DBA sign-off on the read-only SQL Server account, then create the AI MongoDB database and its collections '
    '( summaries , llm_calls , summary_edits ) with their indexes on Azure Cosmos DB for MongoDB. Hard precondition for '
    'everything downstream.',
    1, 'S11 · B Phase 1 — MongoDB collections replace the SQL ai.* schema')

S['11'] = sub(S['11'],
    'its own Container Apps service and its own ai.* schema',
    'its own Container Apps service and its own MongoDB database',
    1, 'S11 · B environments — per-env MongoDB database')

S['11'] = sub(S['11'],
    'The AI tier only ever adds rows to its own ai.* schema;',
    'The AI tier only ever writes documents to its own MongoDB collections and never writes to SQL Server at all;',
    1, 'S11 · B fault tolerance — AI writes are MongoDB-only')

S['11'] = sub(S['11'],
    '- Network path + credentials to AWS SQL Server (reads + the new ai.* schema), the .NET Legacy API, and the United CP '
    'Gateway.',
    '- Network path + read-only credentials to AWS SQL Server, plus connectivity to its own MongoDB, the .NET Legacy API, and '
    'the United CP Gateway.',
    1, 'S11 · C Phase 0 — read-only SQL access, writes to MongoDB')

S['11'] = sub(S['11'],
    '- ai.* schema migration applied to SQL Server; AI proxy route deployed',
    '- MongoDB collections and indexes created on Azure Cosmos DB for MongoDB; AI proxy route deployed',
    1, 'S11 · C Phase 0 — MongoDB provisioning replaces SQL migration')

S['12'] = sub(S['12'],
    'read-scoped on inventory and dispatch tables, write access confined to the new ai.* schema; network-restricted to the '
    'service subnet.',
    'read-scoped on inventory and dispatch tables with no write grant at all; every AI write goes to its own MongoDB. '
    'Network-restricted to the service subnet.',
    1, 'S12 · data-store access — SQL account is read-only')

# diagram soup -> figure placeholders
FIGS = []
def figure(caption, note):
    FIGS.append(caption)
    n = len(FIGS)
    return (f'\n> **Figure {n} \u2014 {caption}**\n>\n> *[Paste screenshot here.]* {note} '
            f'Live version: `stream1-unified-architecture.html`.\n')

soup_today = [l for l in S['05'].split('\n') if l.startswith('TECH \u00b7 IN THE APP PAIN TODAY')]
soup_ai    = [l for l in S['05'].split('\n') if l.startswith('TECH \u00b7 IN THE APP AI \u00b7 BEHIND')]
assert len(soup_today) == 1 and len(soup_ai) == 1, (len(soup_today), len(soup_ai))

S['02'] = S['02'].replace('### 2a \u00b7 Unified system diagram\n',
    '### 2a \u00b7 Unified system diagram\n' + figure(
        'Unified system diagram \u00b7 ClimatePros Stream 1',
        'Six zones: clients; the existing FieldJetX platform on AWS; new AWS infrastructure (queue, workers, push); '
        'the new Azure AI stack (FastAPI AI server, MongoDB, vector store); the private on-prem model infra; and the '
        'cross-cutting observability layer.'), 1)

S['02'] = S['02'].replace('### 2b \u00b7 Detailed architecture per use case\n',
    '### 2b \u00b7 Detailed architecture per use case\n' + figure(
        'Use Case A \u2014 detailed architecture (Auto-Dispatch)',
        'Blue = existing \u00b7 unchanged; amber dashed = new \u00b7 this project; purple = toggle/config flow; '
        'green = DB read/write. Entirely within AWS.') + figure(
        'Use Cases B & C \u2014 detailed architecture (shared AI service)',
        'Blue = existing \u00b7 unchanged; amber dashed = new \u00b7 this project; purple = LLM/embedding calls '
        '(client-hosted, off-cloud); green = persist/read. Grey dashed = optional vector index.'), 1)

S['05'] = S['05'].replace(soup_today[0], figure(
        'Use Case B \u2014 the close-out visit today, without AI',
        'Left column = technician steps in the app; right column = where cost arises today '
        '(goes in cold, quality varies by typist, no validation before submit, problems found when expensive).').strip())
S['05'] = S['05'].replace(soup_ai[0], figure(
        'Use Case B \u2014 the same visit with the AI Copilot',
        'Left column = technician actions (unchanged journey); right column = AI work behind the scenes '
        '(briefing builder, prefill + summarisation, analyse pipeline, persist + learn). '
        'Blue = technician action; amber = AI-assisted step.').strip())

S['05'] = S['05'].replace('\U0001F504 New Dispatch \u2192 Assignment\n',
    figure('Use Case A \u2014 assignment loop (trigger to outcome)',
           'The ranked cascade with a 30-second offer window per technician and escalation to a human dispatcher '
           'when the shortlist is exhausted. Steps are written out below.') + '\n', 1)

S['05'] = S['05'].replace('\U0001F527 Four-Source Find \u2192 Allocate\n',
    figure('Use Case C \u2014 four-source find and greedy allocate',
           'Truck \u2192 nearby technicians\u2019 trucks \u2192 branch warehouse \u2192 third-party supplier, then greedy '
           'allocation down the sorted list. Steps are written out below.') + '\n', 1)

# ---------------------------------------------------------------- front matter
FRONT = '''# ClimatePros \u00b7 Stream 1 \u2014 Unified Architecture

Version 1.0 \u2014 Draft for Client Review

Use Case A \u2014 Auto Dispatch   \u00b7   Use Case B \u2014 Closeout Copilot   \u00b7   Use Case C \u2014 Parts Finder

**PREPARED FOR**

ClimatePros

**PREPARED BY**

techjays

**ISSUED**

July 28, 2026

**COMPANION TO**

ClimatePros Stream 1 Scope Document v2.0 (July 21, 2026)

**CLASSIFICATION**

Confidential \u2014 ClimatePros / techjays

---

**Document Control**

| Item | Detail |
|---|---|
| Document | Stream 1 \u2014 Unified Architecture |
| Version | 1.0 \u2014 Draft for Client Review |
| Issued | July 28, 2026 |
| Prepared by | techjays |
| Classification | Confidential \u2014 ClimatePros / techjays |
| Companion to | Stream 1 Scope Document v2.0 (July 21, 2026) \u2014 that document defines *what* is in scope; this one defines *how* it is built. |
| Source | Generated from the `stream1-unified-architecture` design set (sections 1\u201312) |

**How to Read This Document**

  - Sections are numbered 1\u201312 and match the live architecture document one-to-one. Cross-references appear as \u00a7N \u2014 for example \u00a76 Core Logic.
  - **Cloud placement rule, applied throughout:** anything AI-specific runs on **Azure** \u2014 the FastAPI AI server, its MongoDB, and the vector store. Everything else runs on **AWS**: the .NET APIs on EC2, SQL Server, the ElastiCache for Redis dispatch queue, the ECS Fargate workers, and Amazon SNS push. Models stay **on-prem** on ClimatePros hardware. The single cross-cloud hop is the AI request itself (AWS \u2192 Azure).
  - **Use Case A involves no LLM.** It is a deterministic weighted-sum ranking and must stay explainable. Use Cases B and C are AI-assisted, and in both the technician can always override the output.
  - Diagrams appear as **Figure N** placeholders for screenshots from the live HTML document; each carries a caption describing what the figure shows, so the text stands alone without it.
  - Formulas, schemas, scoring constants, API parameters and cost line items are reproduced at full fidelity from the source design, not summarised.
  - Terminology corrected during conversion is listed in **Appendix A**; open items needing ClimatePros confirmation are listed in **Appendix B**.

**Approval**

Approved for ClimatePros:  \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_   Date:  \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_

Approved for techjays:  \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_   Date:  \\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_

---

**Table of Contents**

[TOC]

---

'''

# ---------------------------------------------------------------- appendices
def appendix_a():
    """Compact: group corrections by the term that changed, not by occurrence."""
    groups = {}
    for label, old, new, n in FIX_LOG:
        if label.endswith('already normalised by global pass'):
            continue
        sec = label.split(' \u00b7 ')[0].replace('S', '\u00a7')
        if 'global term' in label:
            key = (old.strip(), new.strip())
        else:
            key = ('__' + label.split(' \u00b7 ', 1)[1], '')
        g = groups.setdefault(key, {'secs': set(), 'n': 0})
        g['secs'].add(sec)
        g['n'] += n

    def secsort(s):
        return sorted(s, key=lambda x: int(re.sub(r'\D', '', x) or 0))

    term_rows, edit_rows = [], []
    for (a, b), g in groups.items():
        where = ', '.join(secsort(g['secs']))
        if a.startswith('__'):
            edit_rows.append(f"| {a[2:]} | {where} |")
        else:
            term_rows.append(f"| `{a}` | `{b}` | {where} | {g['n']} |")
    term_rows.sort()
    edit_rows.sort(key=lambda r: r.split('|')[2])

    return ('## Appendix A \u2014 Corrections applied during conversion\n\n'
            'The source section fragments had drifted apart: \u00a72a, \u00a73 and \u00a74 had been updated to the confirmed cloud placement '
            'while \u00a75 and \u00a77\u2013\u00a712 still carried an earlier Azure-first model. Every correction below applies one rule \u2014 '
            '**AI-specific components on Azure, everything else on AWS** \u2014 together with the AI-datastore decision '
            '(MongoDB on Azure, not an `ai.*` schema on SQL Server). No other source content was altered, and no figures, '
            'formulas or API parameters were changed.\n\n'
            '**Terminology replaced throughout**\n\n'
            '| Was | Now | Sections | Occurrences |\n|---|---|---|---|\n' + '\n'.join(term_rows) + '\n\n'
            '**Statements rewritten** (each corrected a claim that contradicted the cloud rule or the MongoDB decision)\n\n'
            '| Correction | Section |\n|---|---|\n' + '\n'.join(edit_rows) + '\n')

APPENDIX_B = '''## Appendix B \u2014 Open items

Carried from the source sections plus the two conflicts surfaced by this conversion. Each needs a ClimatePros owner before
this document can move from draft to agreed.

| # | Open item | Where | Why it matters |
|---|---|---|---|
| 1 | Dispatch-worker task size: \u00a74 Compute sizing specifies 0.5 vCPU / 1 GB; \u00a710 Cost Projection and \u00a711 Phase 0 both assume 1 vCPU / 2 GB. | \u00a74, \u00a710, \u00a711 | The cost formula and the ECS task definition are built from this number; the two figures give different monthly totals. |
| 2 | Azure re-pricing for the AI lines \u2014 Container Apps, the chosen vector store, and Azure Monitor. | \u00a710 | Those figures are still AWS-sourced rates. Use Case A\u2019s AWS figures now stand as-is. |
| 3 | Vector store selection: \u00a74 lists Azure AI Search / Pinecone as candidates; \u00a73 marks the store experimental; \u00a76 B states the index is out of scope pending evals, while \u00a76 C actively searches it. | \u00a73, \u00a74, \u00a76 | C needs a store at go-live; B only if evals justify it. The selection and the C-only scope should be stated explicitly. |
| 4 | Learning-loop trigger for C: the AI server has no SQL Server connection, so dispatch completion must be pushed to it by the .NET side rather than polled. | \u00a76 C, \u00a77 C | Without a confirmed trigger the self-learning index never updates. |
| 5 | MongoDB collection and index design sign-off with the client DBA (replaces the earlier ai.* DDL approval). | \u00a77 B | Determines query performance for briefing retrieval and the eval dashboards. |
| 6 | Dispatch-assignment trigger mechanism for the B briefing builder. | \u00a75 B, \u00a77 B | The briefing must start building at assignment time to be warm when the technician opens the job. |
| 7 | Per-division lock model: the \u00a72 diagram still shows a per-division lock (`lock:div:*`); the implemented model locks per candidate technician. Diagram redraw pending. | \u00a72, \u00a77 A | The diagram and the implementation disagree on concurrency behaviour. |
| 8 | Cross-cloud network path: site-to-site VPN or VPC-to-VNet peering is the target state; the interim fallback is a public HTTPS endpoint with IP allow-listing / mTLS. | \u00a74 | Security review and the P95 latency budget in \u00a79 both depend on which one ships. |
| 9 | Push token / endpoint ARN is the one new piece of personal data this project stores. | \u00a711, \u00a712 | Needs to be reflected in the PII inventory and retention policy. |
| 10 | `CLAUDE.md` in the source repository still describes the older Azure-first model (\u201cAzure except the AWS SQL Server database\u201d) and names Azure Notification Hubs and Azure Cache for Redis. | repository | Future edits made from that guidance would reintroduce the mismatches corrected here. |
'''

# ---------------------------------------------------------------- assemble
STYLE = ('<style>body{font-family:Arial,Helvetica,sans-serif;line-height:1.45;font-size:11pt}'
         'h1{font-size:26pt}h2{font-size:17pt}h3{font-size:13pt}h4{font-size:11.5pt}h5{font-size:11pt}'
         'table{border-collapse:collapse;width:100%}'
         'th,td{border:1px solid #999;padding:5px 7px;vertical-align:top;font-size:9.5pt}'
         'th{background:#eef2f7;text-align:left}'
         'pre{background:#f4f6f8;border:1px solid #d5dbe2;padding:8px;font-family:"Courier New",monospace;font-size:9pt;'
         'white-space:pre-wrap}code{font-family:"Courier New",monospace;font-size:9.5pt}'
         'blockquote{border-left:3px solid #b9c3cf;margin:10px 0;padding:6px 12px;background:#f7f9fb}'
         '</style>')

def render(title, md_text):
    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists', 'attr_list'],
                           extension_configs={'toc': {'toc_depth': '2-3', 'permalink': False}})
    return ('<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
            f'<title>{title}</title>' + STYLE + '</head><body>\n'
            + md.convert(md_text) + '\n</body></html>\n')

BODY = '\n\n'.join(S[n] for n in ['01','02','03','04','05','06','07','08','09','10','11','12'])
FULL = FRONT + BODY + '\n\n---\n\n' + appendix_a() + '\n---\n\n' + APPENDIX_B

# --- single complete file (for File > Open in Google Docs, or the repo) --------
full_html = render('ClimatePros \u00b7 Stream 1 \u2014 Unified Architecture', FULL)
(OUT / 'stream1-unified-architecture-doc.html').write_text(full_html, encoding='utf-8')

# --- two-part split, because Drive uploads are inline-only --------------------
PART1_SECS = ['01','02','03','04','05','06','07']
PART2_SECS = ['08','09','10','11','12']

SPLIT_NOTE_1 = ('\n> **This is Part 1 of 2.** Part 1 covers \u00a71\u2013\u00a77 (orientation, architecture, technology, '
                'infrastructure, flows, core logic, data & schema). Part 2 covers \u00a78\u2013\u00a712 (API reference, '
                'observability & evals, cost, onboarding & fault tolerance, non-goals & PII) plus Appendices A and B. '
                'Cross-references written as \u00a7N point to the section with that number in whichever part holds it.\n')

FRONT2 = ('# ClimatePros \u00b7 Stream 1 \u2014 Unified Architecture \u2014 Part 2\n\n'
          'Version 1.0 \u2014 Draft for Client Review \u00b7 Confidential \u2014 ClimatePros / techjays \u00b7 July 28, 2026\n\n'
          '> **This is Part 2 of 2.** It continues from Part 1, which carries the cover page, Document Control, '
          '"How to Read This Document", Approval, and \u00a71\u2013\u00a77. This part covers \u00a78\u2013\u00a712 and the two '
          'appendices. The cloud placement rule stated in Part 1 applies throughout: AI-specific components on Azure, '
          'everything else on AWS, models on-prem.\n\n---\n\n'
          '**Table of Contents \u2014 Part 2**\n\n[TOC]\n\n---\n\n')

part1_md = FRONT.replace('**Table of Contents**', SPLIT_NOTE_1 + '\n**Table of Contents \u2014 Part 1**') \
           + '\n\n'.join(S[n] for n in PART1_SECS)
part2_md = FRONT2 + '\n\n'.join(S[n] for n in PART2_SECS) + '\n\n---\n\n' + appendix_a() + '\n---\n\n' + APPENDIX_B

p1 = render('ClimatePros \u00b7 Stream 1 \u2014 Unified Architecture \u2014 Part 1', part1_md)
p2 = render('ClimatePros \u00b7 Stream 1 \u2014 Unified Architecture \u2014 Part 2', part2_md)
(OUT / 'part1.html').write_text(p1, encoding='utf-8')
(OUT / 'part2.html').write_text(p2, encoding='utf-8')

print(f'full  : {len(full_html):>7,} bytes  h2={full_html.count("<h2")} tables={full_html.count("<table")}')
print(f'part1 : {len(p1):>7,} bytes  h2={p1.count("<h2")} tables={p1.count("<table")}')
print(f'part2 : {len(p2):>7,} bytes  h2={p2.count("<h2")} tables={p2.count("<table")}')
print(f'figures={len(FIGS)}  corrections logged={len(FIX_LOG)}')
