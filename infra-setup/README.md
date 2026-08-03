# Stream 1 — AWS Infra Setup (CLI runbook)

Provision the **new AWS infrastructure** for Stream 1 (Use Case A · Auto-Dispatch) on top of the
**existing** ClimatePros / FieldJetX platform. Every step is an `aws` CLI command — no console
clicking, so the same run is repeatable per environment.

Source of truth for the design: [`../unified-hld.html`](../unified-hld.html) ·
`../sections/03.html` (Technology Stack) · `../sections/04.html` (Infrastructure) ·
`../sections/10.html` (Cost).

---

## Scope

| | |
|---|---|
| **In scope** | New AWS resources: ElastiCache for Redis, ECR, ECS Fargate, SNS push, IAM, Secrets Manager, security groups, CloudWatch |
| **Reused as-is** | EC2 .NET host, SQL Server (RDS), VPC/subnets/NAT, load balancer + WAF — **discover, never create** |
| **One change to existing** | Attach an inline policy to the EC2 instance role so the .NET scale-monitor can call `ecs:UpdateService` (see `03-iam.md`) — needs client approval |
| **Out of scope** | Azure AI stack (Container Apps, Cosmos DB, vector store), on-prem models (LiteLLM / qwen3-vl-moe / bge-m3), Gemini. Only the **AWS side of the cross-cloud seam** is covered (`10-cross-cloud-seam.md`) |

Use Cases **B** and **C** add no new AWS infrastructure — their tier is Azure. The AWS-side work for
B/C is a `.NET` route on the existing EC2 host plus outbound egress.

---

## Read in this order

| # | File | Service | New? |
|---|---|---|---|
| 00 | [`00-aws-cli-setup.md`](00-aws-cli-setup.md) | AWS CLI on macOS + Windows, profiles, first login | — |
| 01 | [`01-existing-vs-new.md`](01-existing-vs-new.md) | Discover existing infra, record IDs, naming + tags | — |
| 02 | [`02-networking.md`](02-networking.md) | Security groups, subnets, egress path | new SGs |
| 03 | [`03-iam.md`](03-iam.md) | Task roles, execution role, EC2 role addition | new |
| 04 | [`04-secrets-manager.md`](04-secrets-manager.md) | Secrets Manager | new |
| 05 | [`05-elasticache-redis.md`](05-elasticache-redis.md) | Amazon ElastiCache for Redis — dispatch queue | new |
| 06 | [`06-ecr.md`](06-ecr.md) | Amazon ECR — worker image registry | new |
| 07 | [`07-ecs-fargate.md`](07-ecs-fargate.md) | ECS Fargate — dispatch workers (0→1) | new |
| 08 | [`08-sns-push.md`](08-sns-push.md) | Amazon SNS — APNs / FCM push | new |
| 09 | [`09-cloudwatch.md`](09-cloudwatch.md) | CloudWatch logs, alarms, OTel | new |
| 10 | [`10-cross-cloud-seam.md`](10-cross-cloud-seam.md) | AWS → Azure AI-server hop (AWS side only) | new |
| 11 | [`11-service-communication.md`](11-service-communication.md) | **How everything talks** — hops, ports, auth | map |
| 12 | [`12-verify-and-teardown.md`](12-verify-and-teardown.md) | End-to-end smoke test, cost check, teardown | — |

Order matters: 02→03→04 create the things 05–09 reference. 05 and 06 are independent of each other
and can run in parallel.

---

## Environments

ClimatePros already runs **Dev / Staging / Prod**; Stream 1 mirrors all three. Every command below
takes `$ENV` — run the whole runbook once per environment. Differences:

| | Dev | Staging | Prod |
|---|---|---|---|
| Redis nodes | 1 (no failover) | 1 | 2 (Multi-AZ) |
| Fargate tasks | 0–1 | 0–1 | 0–1 (per §4 sizing) |
| SQL Server | snapshot | restricted replica | live system of record |
| Secrets | separate path `cp/dev/...` | `cp/staging/...` | `cp/prod/...` |

---

## Cost of the new AWS tier

From `../sections/10.html` (us-east-1 rates), Prod:

| Item | Monthly |
|---|---|
| ElastiCache `cache.t4g.small`, always on | ~$23 (×2 if Multi-AZ ⇒ ~$47) |
| ECS Fargate, 2 tasks × 8 h/day | ~$24 (→ **$0** when a division toggles off) |
| SNS push (~75k/mo) | $0 — inside the 1M free tier |
| CloudWatch logs + alarms | low single digits |
| ECR storage | cents |
| Cross-cloud egress (B/C only) | TBD — no source figure exists |

**Fixed floor ≈ $23–47/mo.** Only Fargate is variable — that is the point of scale-to-zero.
Do **not** add interface VPC endpoints unless the VPC has no NAT gateway: six endpoints × 2 AZ is
≈ $88/mo, more than everything else combined. See `02-networking.md`.

---

## Decisions already made (don't re-open)

- **Message broker = Amazon ElastiCache for Redis, Redis Streams.** The `Redis Streams / Amazon MQ /
  Amazon SQS` TBD in the HLD diagram is resolved — §3/§4 name ElastiCache as the decided
  implementation (`XREADGROUP` / `XACK` / `XCLAIM`, division locks, per-technician reply `BLPOP`).
- **Redis cluster mode stays DISABLED.** Streams + `BLPOP` + multi-key division locks; cluster mode
  would introduce cross-slot failures.
- **Auto-Dispatch never leaves AWS.** Workers read/write SQL Server in-VPC. The only cross-cloud hop
  is the B/C AI request from the .NET proxy.
- **Use Case A has no LLM.** Nothing in this runbook provisions model infrastructure.
