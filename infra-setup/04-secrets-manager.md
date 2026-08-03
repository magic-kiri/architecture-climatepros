# 04 · AWS Secrets Manager — credentials

**Status:** NEW · **Cloud:** AWS · **Used by:** UC-A (worker), UC-B/C (AI-proxy route)

Every credential the new tier needs, in one place, injected into the container by ECS at start-up.
No credential in an environment variable in the task definition, none in the image, none in git.

---

## Secrets to create

| Name | Holds | Read by |
|---|---|---|
| `cp/$ENV/dispatch/redis-auth-token` | ElastiCache AUTH token | worker + .NET host |
| `cp/$ENV/dispatch/sqlserver` | SQL Server user/pass/host/db | worker |
| `cp/$ENV/push/apns` | APNs signing key / cert | SNS platform app (`08`) |
| `cp/$ENV/push/fcm` | FCM v1 service-account JSON | SNS platform app (`08`) |
| `cp/$ENV/ai-server` | Azure AI-server base URL + client credential | .NET AI proxy (`10`) |

`$ENV` in the path is what keeps Dev / Staging / Prod apart — the IAM policies in `03` are scoped to
`cp/ENV/*`, so a Dev role cannot read Prod secrets.

---

## Steps

### 1. Redis auth token

Generate a strong token (16–128 chars, no `/ " @` or spaces — ElastiCache rejects them):

```bash
export REDIS_AUTH_TOKEN=$(openssl rand -base64 36 | tr -d '/+=@" ')
```

Windows PowerShell:

```powershell
$env:REDIS_AUTH_TOKEN = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})
```

Store it — `05` needs the same value when it creates the replication group:

```bash
aws secretsmanager create-secret \
  --name cp/$ENV/dispatch/redis-auth-token \
  --description "Stream 1 dispatch queue AUTH token" \
  --secret-string "$REDIS_AUTH_TOKEN" \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

### 2. SQL Server credentials

Ask ClimatePros for a **dedicated login for the dispatch worker** — not the .NET app's login. It needs
read/write on the dispatch and assignment tables only.

Write `sqlserver.json` (delete the file afterwards):

```json
{
  "host": "xxx.rds.amazonaws.com",
  "port": 1433,
  "database": "FieldJetX",
  "username": "svc_dispatch_worker",
  "password": "..."
}
```

```bash
aws secretsmanager create-secret \
  --name cp/$ENV/dispatch/sqlserver \
  --secret-string file://sqlserver.json \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

rm sqlserver.json      # PowerShell: Remove-Item sqlserver.json
```

`file://` is not optional on Windows — inline JSON is mangled by PowerShell quoting.

### 3. Push credentials

Placeholders now, real values from the ClimatePros Apple/Firebase accounts before `08`:

```bash
aws secretsmanager create-secret --name cp/$ENV/push/apns --secret-string file://apns.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws secretsmanager create-secret --name cp/$ENV/push/fcm --secret-string file://fcm-service-account.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

### 4. AI-server endpoint (B and C)

Only the .NET AI-proxy route reads this. No AWS-side worker touches it.

```bash
aws secretsmanager create-secret --name cp/$ENV/ai-server --secret-string file://ai-server.json \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=BC Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

`ai-server.json`:

```json
{ "base_url": "https://<ai-server>.azurecontainerapps.io", "api_key": "...", "timeout_s": 30 }
```

---

## How the worker receives them

In the task definition (`07`), under `secrets` — never `environment`:

```json
"secrets": [
  { "name": "REDIS_AUTH_TOKEN", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/redis-auth-token" },
  { "name": "SQL_USERNAME",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:username::" },
  { "name": "SQL_PASSWORD",     "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/dispatch/sqlserver:password::" }
]
```

The `:key::` suffix pulls a single field out of a JSON secret. The trailing `::` (empty
version-stage, empty version-id) is required — omitting it is the usual cause of
`ResourceNotFoundException` at task start.

---

## Verify

```bash
aws secretsmanager list-secrets \
  --filters Key=name,Values=cp/$ENV/ \
  --query 'SecretList[].{Name:Name,Changed:LastChangedDate}' --output table

# value check (prints the secret — don't do this on a shared screen)
aws secretsmanager get-secret-value --secret-id cp/$ENV/dispatch/redis-auth-token \
  --query 'SecretString' --output text
```

---

## Talks to

Nothing calls Secrets Manager on its own. It is **read** over HTTPS by: the ECS task-exec role at task
start-up, the worker task role at runtime, and the .NET host for the AI-server credential.

---

## Cost

$0.40 per secret per month + $0.05 per 10,000 API calls. Five secrets ≈ **$2/mo**. Retrieval happens
once per task start, not per request.

---

## Gotchas

- Deleted secrets sit in a 7–30 day recovery window and the **name stays reserved**. To recreate
  immediately: `aws secretsmanager delete-secret --secret-id <name> --force-delete-without-recovery`.
- Rotating the Redis token means updating the secret **and** running
  `aws elasticache modify-replication-group --auth-token <new> --auth-token-update-strategy ROTATE`.
  Two steps, in that order.
- Don't put the SQL password in an ECS `environment` entry — it shows up in
  `aws ecs describe-task-definition` for anyone with read access.

**Next:** [`05-elasticache-redis.md`](05-elasticache-redis.md)
