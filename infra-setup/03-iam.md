# 03 · IAM — roles for the workers and the scale monitor

**Status:** NEW (2 roles) + **1 change to existing** · **Cloud:** AWS · **Used by:** UC-A

Three identities:

| Role | Who assumes it | What it may do |
|---|---|---|
| `cp-$ENV-dispatch-task-exec` | ECS agent, before the container starts | pull the ECR image, read secrets, create log streams |
| `cp-$ENV-dispatch-task` | the worker process itself | `sns:Publish`, read secrets, emit traces |
| *existing EC2 instance role* | the .NET Microservices API | `ecs:UpdateService` — the scale monitor toggling workers 0→1 |

Redis auth is a token from Secrets Manager, not IAM. SQL Server auth is credentials from Secrets
Manager. Neither role gets database permissions.

---

## Prereqs

`vars.sh` loaded, including `EC2_ROLE_NAME` resolved in `01`.

---

## Steps

### 1. Trust policy file (shared by both new roles)

`trust-ecs-tasks.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
```

### 2. Task execution role

```bash
aws iam create-role --role-name cp-$ENV-dispatch-task-exec \
  --assume-role-policy-document file://trust-ecs-tasks.json \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam attach-role-policy --role-name cp-$ENV-dispatch-task-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

Add secret-reading (the task definition injects secrets at start-up). `policy-exec-secrets.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:GetSecretValue"],
    "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/*"
  }]
}
```

```bash
aws iam put-role-policy --role-name cp-$ENV-dispatch-task-exec \
  --policy-name read-stream1-secrets --policy-document file://policy-exec-secrets.json
```

Replace `REGION`/`ACCOUNT`/`ENV` in the file before applying — IAM does not expand shell variables.

### 3. Task role (the worker's own permissions)

```bash
aws iam create-role --role-name cp-$ENV-dispatch-task \
  --assume-role-policy-document file://trust-ecs-tasks.json \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

`policy-worker.json` — push, secrets, traces. Nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PushToTechnicianPhones",
      "Effect": "Allow",
      "Action": ["sns:Publish", "sns:GetEndpointAttributes", "sns:SetEndpointAttributes"],
      "Resource": [
        "arn:aws:sns:REGION:ACCOUNT:endpoint/APNS/cp-ENV-fieldjetx-ios/*",
        "arn:aws:sns:REGION:ACCOUNT:endpoint/GCM/cp-ENV-fieldjetx-android/*"
      ]
    },
    {
      "Sid": "ReadRuntimeSecrets",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/*"
    },
    {
      "Sid": "Telemetry",
      "Effect": "Allow",
      "Action": [
        "logs:PutLogEvents", "logs:CreateLogStream",
        "xray:PutTraceSegments", "xray:PutTelemetryRecords",
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

```bash
aws iam put-role-policy --role-name cp-$ENV-dispatch-task \
  --policy-name dispatch-worker --policy-document file://policy-worker.json
```

### 4. ⚠️ The one change to existing infrastructure — scale-monitor permission

The .NET Microservices API's `POST /divisions/{id}/toggle` route flips the worker service between
`desiredCount` 0 and 1. That call needs `ecs:UpdateService` on **exactly one service ARN**.

`policy-ecs-scale.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ecs:UpdateService", "ecs:DescribeServices", "ecs:ListTasks"],
    "Resource": "arn:aws:ecs:REGION:ACCOUNT:service/cp-ENV-dispatch/cp-ENV-dispatch-workers"
  }]
}
```

```bash
aws iam put-role-policy --role-name $EC2_ROLE_NAME \
  --policy-name cp-$ENV-dispatch-scale-monitor --policy-document file://policy-ecs-scale.json
```

> **Get client approval for this one command.** It is an inline policy added to a role the existing
> platform already uses — additive, removable with a single `delete-role-policy`, and scoped to one
> service ARN. It does not alter any existing permission. Run it **after** `07` creates the service so
> the ARN resolves.

---

## Verify

```bash
aws iam get-role --role-name cp-$ENV-dispatch-task-exec --query 'Role.Arn' --output text
aws iam get-role --role-name cp-$ENV-dispatch-task      --query 'Role.Arn' --output text
aws iam list-role-policies --role-name cp-$ENV-dispatch-task --output text
aws iam list-role-policies --role-name $EC2_ROLE_NAME --output text   # scale-monitor policy present
```

Dry-run the scale-monitor grant from the EC2 host itself:

```bash
aws ecs describe-services --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers \
  --query 'services[0].desiredCount' --output text
```

---

## Talks to

- **Task exec role** → ECR, Secrets Manager, CloudWatch Logs (control plane, at task start)
- **Task role** → SNS, Secrets Manager, X-Ray/CloudWatch (runtime)
- **EC2 role** → ECS control plane (`UpdateService`) — the scale toggle in `11`

---

## Gotchas

- IAM is **global** — no `--region`. It is also eventually consistent: a role created seconds ago can
  fail `register-task-definition`. Retry once.
- Two distinct roles is not ceremony: the exec role is used by the ECS agent *before* your code runs,
  the task role *by* your code. Collapsing them hands the container image-pull rights it never needs.
- Placeholders `REGION` / `ACCOUNT` / `ENV` inside the JSON files must be edited by hand.
- ElastiCache IAM auth (Redis 7+) is an alternative to the auth token. `04` uses the token — it is
  what the worker's `redis.asyncio` client expects and matches §3.

**Next:** [`04-secrets-manager.md`](04-secrets-manager.md)
