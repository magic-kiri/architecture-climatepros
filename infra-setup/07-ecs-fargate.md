# 07 · AWS ECS Fargate — Auto-Dispatch workers

**Status:** NEW · **Cloud:** AWS · **Used by:** UC-A only

The async worker pool. Consumes dispatches from the Redis stream, runs the **deterministic weighted-sum
ranking** (distance/ETA · prior-visit familiarity · time-until-free · job priority), pushes accept/decline
offers via SNS, blocks on the technician's reply, writes the assignment to SQL Server. **No LLM in this
path.**

Scales **0 → 1** on the Auto-Dispatch toggle — a division with the feature off costs $0.

---

## Prereqs

`02` (`WORKER_SG_ID`, `SUBNET_A/B`) · `03` (both task roles) · `04` (secrets) · `05` (`REDIS_ENDPOINT`)
· `06` (image URI).

---

## Steps

### 1. Log group first — a task with nowhere to log fails to start

```bash
aws logs create-log-group --log-group-name /ecs/cp-$ENV-dispatch-worker \
  --tags Project=stream1,UseCase=A,Env=$ENV,ManagedBy=techjays

aws logs put-retention-policy --log-group-name /ecs/cp-$ENV-dispatch-worker --retention-in-days 30
```

### 2. Cluster

```bash
aws ecs create-cluster --cluster-name cp-$ENV-dispatch \
  --settings name=containerInsights,value=enabled \
  --tags key=Project,value=stream1 key=UseCase,value=A key=Env,value=$ENV key=ManagedBy,value=techjays
```

`containerInsights` is what makes the §9 dashboards possible. Note the lowercase `key=`/`value=` — the
ECS API differs from EC2's `Key=`/`Value=` here.

### 3. Task definition

`taskdef.json` — replace `REGION`, `ACCOUNT`, `ENV`, the image tag and `REDIS_ENDPOINT`:

```json
{
  "family": "cp-ENV-dispatch-worker",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "runtimePlatform": { "cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX" },
  "executionRoleArn": "arn:aws:iam::ACCOUNT:role/cp-ENV-dispatch-task-exec",
  "taskRoleArn": "arn:aws:iam::ACCOUNT:role/cp-ENV-dispatch-task",
  "containerDefinitions": [
    {
      "name": "dispatch-worker",
      "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/cp/dispatch-worker:ENV-0.1.0",
      "essential": true,
      "environment": [
        { "name": "ENVIRONMENT",        "value": "ENV" },
        { "name": "REDIS_HOST",         "value": "cp-ENV-dispatch-redis.xxxx.ng.0001.use1.cache.amazonaws.com" },
        { "name": "REDIS_PORT",         "value": "6379" },
        { "name": "REDIS_TLS",          "value": "true" },
        { "name": "DISPATCH_STREAM",    "value": "dispatch:stream" },
        { "name": "CONSUMER_GROUP",     "value": "dispatch-workers" },
        { "name": "MAX_CONCURRENT_DISPATCHES", "value": "20" },
        { "name": "SNS_APP_IOS_ARN",     "value": "arn:aws:sns:REGION:ACCOUNT:app/APNS/cp-ENV-fieldjetx-ios" },
        { "name": "SNS_APP_ANDROID_ARN", "value": "arn:aws:sns:REGION:ACCOUNT:app/GCM/cp-ENV-fieldjetx-android" },
        { "name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": "http://localhost:4317" }
      ],
      "secrets": [
        { "name": "REDIS_AUTH_TOKEN", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/redis-auth-token" },
        { "name": "SQL_HOST",         "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:host::" },
        { "name": "SQL_DATABASE",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:database::" },
        { "name": "SQL_USERNAME",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:username::" },
        { "name": "SQL_PASSWORD",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:password::" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/cp-ENV-dispatch-worker",
          "awslogs-region": "REGION",
          "awslogs-stream-prefix": "worker"
        }
      },
      "stopTimeout": 60
    }
  ]
}
```

```bash
aws ecs register-task-definition --cli-input-json file://taskdef.json
```

**Sizing note.** `1024/2048` (1 vCPU / 2 GB) matches the §10 cost model — $0.04937/task-hour. §4 gives
a smaller baseline of 0.5 vCPU / 1 GB (`"cpu": "512", "memory": "1024"`), roughly half the rate. Start
at `512/1024` in Dev, and only move Prod up if the concurrency ceiling is actually hit. Either way,
`MAX_CONCURRENT_DISPATCHES=20` per task is what §3 specifies.

`stopTimeout: 60` gives an in-flight dispatch time to `XACK` or release its division lock before SIGKILL
— without it, a deploy can strand a lock until its TTL expires.

### 4. Service — created at zero

```bash
aws ecs create-service \
  --cluster cp-$ENV-dispatch \
  --service-name cp-$ENV-dispatch-workers \
  --task-definition cp-$ENV-dispatch-worker \
  --desired-count 0 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$WORKER_SG_ID],assignPublicIp=DISABLED}" \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=0" \
  --enable-execute-command \
  --tags key=Project,value=stream1 key=UseCase,value=A key=Env,value=$ENV key=ManagedBy,value=techjays
```

Why these flags:

- `--desired-count 0` — the toggle turns it on, not the deploy. Also means a broken image costs nothing.
- `assignPublicIp=DISABLED` — required by the §4 network model. Egress goes through NAT (`02`).
- `minimumHealthyPercent=0` — a queue consumer has no availability requirement during deploys.
- `deploymentCircuitBreaker` — a crash-looping image rolls back instead of retrying forever.
- `--enable-execute-command` — `aws ecs execute-command` shell into a running task for debugging.

**Now run `03` step 4** — the service ARN it needs exists.

### 5. Scale it — what the .NET toggle route does

```bash
# on
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 1
aws ecs wait services-stable --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers

# off
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 0
```

`POST /divisions/{id}/toggle` on the .NET Microservices API makes exactly this call through the AWS SDK,
using the EC2 instance role from `03` step 4. There is no autoscaling policy — the toggle is the only
scaling signal.

---

## Verify

```bash
aws ecs describe-services --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers \
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount,TaskDef:taskDefinition}' \
  --output table

# with desired-count 1: is it actually up
aws ecs list-tasks --cluster cp-$ENV-dispatch --service-name cp-$ENV-dispatch-workers --query 'taskArns' --output text

# first logs — should show the consumer group being created
aws logs tail /ecs/cp-$ENV-dispatch-worker --since 10m --follow
```

Task stuck in `PENDING` → `describe-tasks` and read `stoppedReason`:

| `stoppedReason` | Cause |
|---|---|
| `CannotPullContainerError` | egress path — `02` step 5 |
| `ResourceInitializationError: ... secretsmanager` | exec-role policy or a missing `::` suffix (`04`) |
| `exec format error` | ARM image on an X86_64 task (`06`) |

---

## Talks to

| Direction | Peer | Protocol | Auth |
|---|---|---|---|
| out | ElastiCache Redis | 6379 TLS | AUTH token from Secrets Manager |
| out | SQL Server (RDS) | 1433 | SQL login from Secrets Manager |
| out | Amazon SNS | 443 | task-role IAM (`aioboto3`) |
| out | CloudWatch Logs / X-Ray | 443 | task-role IAM |
| out | ECR + Secrets Manager | 443 | exec-role IAM, at start-up |
| in | **nothing** | — | no listener, no load balancer |

The worker never talks to Azure, never talks to a phone directly, and is never called by the .NET API —
coordination happens entirely through Redis. Full map: [`11-service-communication.md`](11-service-communication.md).

---

## Cost

$0.04048 per vCPU-hour + $0.004445 per GB-hour ⇒ **$0.04937 per task-hour** at 1 vCPU / 2 GB (§10).

| Scenario | 2 tasks | Monthly |
|---|---|---|
| Light — 2 h/day | | ~$6 |
| 8 h/day | | ~$24 |
| 24×7 | | ~$71 |
| Toggle off | 0 tasks | **$0** |

---

## Gotchas

- Updating the task definition creates a **new revision**; the service keeps the old one until you
  `update-service --task-definition cp-$ENV-dispatch-worker` (unqualified family = latest).
- Two tasks in the same consumer group is fine and intended — Redis Streams distributes entries, and the
  per-division `SETNX` lock prevents two workers dispatching the same division.
- Don't attach a load balancer or a health check. There is nothing to health-check; `runningCount` and
  the queue-depth alarm in `09` are the liveness signals.
- Fargate has valid CPU/memory pairs only. `1024` CPU accepts 2–8 GB; `512` accepts 1–4 GB. An invalid
  pair is rejected at `register-task-definition`.

**Next:** [`08-sns-push.md`](08-sns-push.md)
