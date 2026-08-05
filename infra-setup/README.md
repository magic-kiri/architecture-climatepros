# Stream 1 — AWS Infra Setup (CLI runbook)

Provision a **standalone test AWS environment** for Stream 1 (Use Case A · Auto-Dispatch) — its own
VPC, ECS Fargate service, and ElastiCache Redis queue, plus the CI/CD pipeline that deploys to it.
Every step is an `aws` CLI command — no console clicking, so the same run is repeatable per
environment (`$ENV` = `dev` / `test` / `prod`).

Source of truth for the design: [`../unified-hld.html`](../unified-hld.html) ·
`../sections/03.html` (Technology Stack) · `../sections/04.html` (Infrastructure) ·
`../sections/10.html` (Cost).

---

## Read in this order

| # | File | Covers | Prereq |
|---|---|---|---|
| 00 | [`00-aws-cli-setup.md`](00-aws-cli-setup.md) | AWS CLI on macOS + Windows, access keys, profiles, MFA session | — |
| 01 | [`01-ecs-redis-setup.md`](01-ecs-redis-setup.md) | VPC, subnets, security groups, Secrets Manager, IAM task roles, ElastiCache Redis, ECR, ECS cluster/task def/service, verify, cost, teardown | 00 |
| 02 | [`02-cicd-setup.md`](02-cicd-setup.md) | Deploy IAM user, GitHub Actions **or** Azure DevOps pipeline (build → ECR → ECS deploy) | 01 through §7 |

`01` is **standalone** — its own VPC, nothing discovered or reused from the existing FieldJetX
platform. Connecting this to the existing VPC / SQL Server is a later step, not covered here.
`02` only adds the CD pipeline and its IAM user; it changes nothing else in the running system.

---

## What gets built

| Built by | Name |
|---|---|
| VPC + 2 subnets + internet gateway | `cp-$ENV-vpc` |
| Security groups (2) | `cp-$ENV-workers`, `cp-$ENV-redis` |
| Secret | `cp/$ENV/redis-auth-token` |
| IAM roles (2) | `cp-$ENV-task-exec`, `cp-$ENV-task` |
| ElastiCache Redis | `cp-$ENV-dispatch-redis` |
| ECR repo | `cp/dispatch-worker` |
| ECS cluster / task def / service | `cp-$ENV-dispatch` |
| IAM user + access key (CD) | `cp-$ENV-cicd-deploy` |
| Pipeline definition (CD) | GitHub: `.github/workflows/deploy.yml` · Azure DevOps: `azure-pipelines.yml` |

Everything above is new and deletable — each file's teardown section at the bottom removes what it
created.

---

## Cost

From `01-ecs-redis-setup.md` (us-east-1 rates):

| Item | Monthly |
|---|---|
| ElastiCache `cache.t4g.small`, always on | ~$23 (×2 with failover ⇒ ~$47) |
| ECS Fargate, 2 tasks × 8 h/day at 1 vCPU / 2 GB | ~$24 — **$0** when toggled off |
| VPC, subnets, internet gateway | $0 |
| ECR storage, CloudWatch logs | a few dollars |

Fixed floor ≈ **$23/mo** — Redis, because the queue must survive between dispatches. Everything else
scales to zero. Adding a NAT gateway later adds ~$32/mo before any traffic.

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
- **CD auth is one IAM user + long-lived access key, not OIDC.** See `02-cicd-setup.md` §1 — the
  tradeoff is a key that doesn't expire on its own versus one that's scoped per-provider.
