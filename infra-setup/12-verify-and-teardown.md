# 12 · Verify end-to-end, then know how to tear it down

**Creates nothing.** Two jobs: prove the new tier works as one system, and be able to remove it cleanly.

---

## Inventory check — is everything there?

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=stream1 Key=Env,Values=$ENV \
  --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n' | sort
```

Expected, per environment:

| Resource | Count |
|---|---|
| ElastiCache replication group | 1 |
| ECR repository | 1 (shared across envs) |
| ECS cluster + service | 1 + 1 |
| SNS platform applications | 2 (iOS, Android) + 1 alarm topic |
| Secrets | 5 |
| IAM roles | 2 new + 1 policy on the existing EC2 role |
| Security groups | 2 |
| Log groups | 3 |
| Alarms | 4 |

IAM roles and log groups don't appear in the tagging API for every resource type — check them directly:

```bash
aws iam list-roles --query 'Roles[?starts_with(RoleName,`cp-`)].RoleName' --output text
aws logs describe-log-groups --log-group-name-prefix /ecs/cp-$ENV --query 'logGroups[].logGroupName' --output text
```

---

## Smoke test — one dispatch through the whole loop

Run in order. Each step is a checkpoint; stop at the first failure and go back to the file named.

**1 · Redis reachable, TLS + AUTH working** (`05`) — from the EC2 host, not your laptop:

```bash
redis-cli -h $REDIS_ENDPOINT -p 6379 --tls -a "$REDIS_AUTH_TOKEN" PING     # PONG
```

**2 · Worker starts and joins the consumer group** (`07`):

```bash
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 1
aws ecs wait services-stable --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers
aws logs tail /ecs/cp-$ENV-dispatch-worker --since 5m
```

Logs should show the Redis connection and `XGROUP CREATE` (or "group already exists").

**3 · Consumer group registered** (`05`):

```bash
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XINFO GROUPS dispatch:stream
# consumers >= 1, pending 0
```

**4 · Queue a real dispatch** — via the .NET API, not by hand. Confirm the entry is consumed:

```bash
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XLEN dispatch:stream
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XPENDING dispatch:stream dispatch-workers
```

Pending should go to 0 once the dispatch resolves. Pending stuck > 0 with a consumer attached means the
worker is failing after `XREADGROUP` — read the logs.

**5 · Push arrives on a real phone** (`08`) — the actual proof that hops 6 and 7 work:

```bash
aws sns publish --target-arn <endpoint-arn> \
  --message '{"APNS":"{\"aps\":{\"alert\":\"Dispatch offer - smoke test\"}}"}' \
  --message-structure json
```

**6 · Accept writes the assignment** (`07` hop 5) — tap Accept in the app, then check the assignment row
in SQL Server and confirm `XPENDING` dropped to 0 and the division lock key is gone.

**7 · Scale to zero costs nothing**:

```bash
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 0
aws ecs describe-services --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers \
  --query 'services[0].{Desired:desiredCount,Running:runningCount}' --output table
```

Redis keeps the stream; Fargate billing stops.

**8 · The toggle route does the same thing** (`03` step 4) — `POST /divisions/{id}/toggle` from the web
console, then confirm `desiredCount` flipped. This proves the EC2 role policy landed.

**9 · Alarms are live** (`09`):

```bash
aws cloudwatch describe-alarms --alarm-name-prefix cp-$ENV-dispatch \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Actions:length(AlarmActions)}' --output table
```

`Actions` must be ≥ 1 on every row, and the email subscription confirmed.

---

## Cost check after one week

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-08-01,End=2026-08-08 \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Tags":{"Key":"Project","Values":["stream1"]}}' \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output table
```

Against §10: ElastiCache ~$23/mo (×2 if Multi-AZ) is the fixed floor; Fargate tracks toggle hours; SNS
$0 inside the free tier. If the total is far above that, the likely causes are interface VPC endpoints
(`02` step 5) or a log group with no retention policy (`09`).

---

## Teardown

> **Warning:** the commands below permanently delete the new Stream 1 AWS infrastructure. Run them only
> against a Dev or Staging environment, or after the client has explicitly decommissioned Prod. Confirm
> `$ENV` before every command — a mistyped env deletes the wrong environment's dispatch queue.

Order matters — dependents first.

```bash
# 1. stop and delete the ECS service, then the cluster
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 0
aws ecs delete-service  --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --force
aws ecs delete-cluster  --cluster cp-$ENV-dispatch

# 2. ElastiCache — take a final snapshot first
aws elasticache delete-replication-group --replication-group-id cp-$ENV-dispatch-redis \
  --final-snapshot-identifier cp-$ENV-dispatch-final
aws elasticache wait replication-group-deleted --replication-group-id cp-$ENV-dispatch-redis
aws elasticache delete-cache-subnet-group    --cache-subnet-group-name cp-$ENV-dispatch-redis-subnets
aws elasticache delete-cache-parameter-group --cache-parameter-group-name cp-$ENV-dispatch-redis7

# 3. SNS
aws sns delete-platform-application --platform-application-arn $SNS_APP_IOS_ARN
aws sns delete-platform-application --platform-application-arn $SNS_APP_ANDROID_ARN
aws sns delete-topic --topic-arn $ALARM_TOPIC

# 4. revoke the ONE change to existing infrastructure
aws iam delete-role-policy --role-name $EC2_ROLE_NAME --policy-name cp-$ENV-dispatch-scale-monitor

# 5. new IAM roles
for R in cp-$ENV-dispatch-task cp-$ENV-dispatch-task-exec; do
  for P in $(aws iam list-role-policies --role-name $R --query 'PolicyNames' --output text); do
    aws iam delete-role-policy --role-name $R --policy-name $P
  done
  for A in $(aws iam list-attached-role-policies --role-name $R --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name $R --policy-arn $A
  done
  aws iam delete-role --role-name $R
done

# 6. secrets (7-day recovery window; add --force-delete-without-recovery to skip it)
for S in dispatch/redis-auth-token dispatch/sqlserver push/apns push/fcm ai-server; do
  aws secretsmanager delete-secret --secret-id cp/$ENV/$S --recovery-window-in-days 7
done

# 7. rules added to EXISTING security groups
aws ec2 revoke-security-group-ingress --group-id $SQL_SG_ID \
  --protocol tcp --port 1433 --source-group $WORKER_SG_ID

# 8. new security groups (after the service is gone, or ENIs still hold them)
aws ec2 delete-security-group --group-id $REDIS_SG_ID
aws ec2 delete-security-group --group-id $WORKER_SG_ID

# 9. logs, alarms, images
aws cloudwatch delete-alarms --alarm-names \
  cp-$ENV-dispatch-redis-evictions cp-$ENV-dispatch-redis-memory \
  cp-$ENV-dispatch-push-failures cp-$ENV-dispatch-worker-errors
aws logs delete-log-group --log-group-name /ecs/cp-$ENV-dispatch-worker
aws ecr delete-repository --repository-name cp/dispatch-worker --force    # only when NO env uses it
```

**Never touched by teardown:** the EC2 host, SQL Server (RDS), the VPC, subnets, NAT gateway, the load
balancer, and any existing security group beyond the single 1433 rule revoked in step 7.

---

## Sign-off checklist

- [ ] `sts get-caller-identity` returns the ClimatePros account, correct region
- [ ] Existing IDs recorded in `vars.sh` — VPC, subnets, EC2 role, SQL endpoint, NAT IP
- [ ] Redis `maxmemory-policy = noeviction`, TLS + AUTH on, cluster mode off
- [ ] Worker image is `linux/amd64`, pinned by tag, pushed to ECR
- [ ] ECS service exists at `desiredCount 0`, `assignPublicIp=DISABLED`
- [ ] Both SNS platform apps created, correct APNs environment per build type
- [ ] One dispatch completed end to end, assignment written, `XPENDING` back to 0
- [ ] Toggle route flips `desiredCount` 0↔1 using the EC2 instance role
- [ ] All four alarms `OK`/`INSUFFICIENT_DATA` with a confirmed notification target
- [ ] Every log group has a retention policy
- [ ] No interface VPC endpoints unless the VPC genuinely has no NAT
- [ ] Client signed off on the single inline policy added to the existing EC2 role
- [ ] Repeated for Dev, Staging, Prod
