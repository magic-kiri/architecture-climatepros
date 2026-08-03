# 01 · ECS Fargate + ElastiCache Redis + CD

**Prereq:** [`00-aws-cli-setup.md`](00-aws-cli-setup.md) done — `aws sts get-caller-identity` works.

**Standalone.** Own VPC, nothing discovered, nothing existing touched. One pass, top to bottom:

```
GitHub push ──► ECR ──► ECS service ──► task ──► ElastiCache Redis (6379 TLS)
   (CD)                (Fargate)
```

| Built here | Name |
|---|---|
| VPC + 2 subnets + internet gateway | `cp-prod-vpc` |
| Security groups (2) | `cp-prod-workers`, `cp-prod-redis` |
| Secret (1) | `cp/prod/redis-auth-token` |
| IAM roles (3) | task-exec, task, github-deploy |
| ElastiCache Redis | `cp-prod-dispatch-redis` |
| ECR repo | `cp/dispatch-worker` |
| ECS cluster / task def / service | `cp-prod-dispatch` |
| CD | GitHub Actions → ECR → ECS |

Everything is new and deletable — teardown at the bottom removes the lot. Connecting to the existing
FieldJetX VPC and SQL Server is a later step, not this one.

---

## 1. Variables

Nothing to discover. Save as `vars.sh` **outside git**, `source vars.sh`, re-source in every new
terminal.

```bash
export AWS_PROFILE=cp-prod
export AWS_REGION=us-east-1
export ENV=prod
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# filled in as you go
export VPC_ID=
export SUBNET_A=
export SUBNET_B=
export WORKER_SG_ID=
export REDIS_SG_ID=
export REDIS_ENDPOINT=
export ECR_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cp/dispatch-worker
```

Tag every resource `Project=stream1 Env=$ENV ManagedBy=techjays` — teardown and cost attribution
depend on it. The commands below already do.

> **Windows.** The inline JSON policies in §5 and §9 are bash-quoted and break in PowerShell. Put that
> JSON in a file with `$AWS_REGION` / `$ACCOUNT_ID` / `$ENV` replaced by hand, and pass
> `--policy-document file://policy.json`. Everything else runs as written — see `00` §"Cross-platform
> rules".

---

## 2. Network

A `/16` with two `/24` subnets in different AZs — ElastiCache requires two AZs, and Fargate wants the
same two.

```bash
export VPC_ID=$(aws ec2 create-vpc --cidr-block 10.42.0.0/16 \
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=cp-prod-vpc},{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' \
  --query 'Vpc.VpcId' --output text)

# ElastiCache endpoints resolve by DNS name — this must be on
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames

export SUBNET_A=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.42.1.0/24 \
  --availability-zone ${AWS_REGION}a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cp-prod-a},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' \
  --query 'Subnet.SubnetId' --output text)

export SUBNET_B=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.42.2.0/24 \
  --availability-zone ${AWS_REGION}b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cp-prod-b},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' \
  --query 'Subnet.SubnetId' --output text)
```

Tasks need outbound 443 to pull the image, read the secret and ship logs. An internet gateway does
that for free; a NAT gateway costs ~$32/mo. Use the gateway:

```bash
export IGW_ID=$(aws ec2 create-internet-gateway \
  --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=cp-prod-igw},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' \
  --query 'InternetGateway.InternetGatewayId' --output text)

aws ec2 attach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID

export RTB_ID=$(aws ec2 create-route-table --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=cp-prod-rtb},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' \
  --query 'RouteTable.RouteTableId' --output text)

aws ec2 create-route --route-table-id $RTB_ID --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --route-table-id $RTB_ID --subnet-id $SUBNET_A
aws ec2 associate-route-table --route-table-id $RTB_ID --subnet-id $SUBNET_B
```

Add `VPC_ID`, `SUBNET_A`, `SUBNET_B`, `IGW_ID`, `RTB_ID` to `vars.sh`.

The tasks get a public IP (§7) so they can reach the gateway — but their security group has **no
inbound rules**, so nothing can reach them. Redis never gets a public IP at all. To move to private
subnets + NAT later, swap the route target and set `assignPublicIp=DISABLED`; nothing else changes.

---

## 3. Security groups

Two groups, one rule.

```bash
# tasks — no inbound at all; nothing calls them, they pull work from Redis
export WORKER_SG_ID=$(aws ec2 create-security-group \
  --group-name cp-$ENV-workers --description "Dispatch Fargate workers" --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' \
  --query 'GroupId' --output text)

export REDIS_SG_ID=$(aws ec2 create-security-group \
  --group-name cp-$ENV-redis --description "Dispatch queue - ElastiCache" --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' \
  --query 'GroupId' --output text)

# workers -> redis
aws ec2 authorize-security-group-ingress --group-id $REDIS_SG_ID \
  --protocol tcp --port 6379 --source-group $WORKER_SG_ID
```

Rules reference **groups, not CIDRs** — they survive subnet changes. Default egress-all stays on the
worker group; that is the 443 the task needs.

Append both IDs to `vars.sh`.

---

## 4. Secret — the Redis auth token

Generate once. The token cannot be changed later without a rotation call, and cannot contain `/ " @`
or spaces.

```bash
export REDIS_AUTH_TOKEN=$(openssl rand -hex 32)

aws secretsmanager create-secret --name cp/$ENV/redis-auth-token \
  --secret-string "$REDIS_AUTH_TOKEN" \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays \
  --query 'ARN' --output text
```

Keep `REDIS_AUTH_TOKEN` in the shell — §6 needs it at creation time. It is **not** in `vars.sh`.

---

## 5. IAM — two task roles

`trust-ecs.json`:

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

**Execution role** — used by the ECS agent *before* your code runs: pull image, read secrets, open the
log stream.

```bash
aws iam create-role --role-name cp-$ENV-task-exec \
  --assume-role-policy-document file://trust-ecs.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam attach-role-policy --role-name cp-$ENV-task-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy --role-name cp-$ENV-task-exec --policy-name read-secrets \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:$AWS_REGION:$ACCOUNT_ID:secret:cp/$ENV/*\"}]}"
```

**Task role** — used *by* the worker process at runtime.

```bash
aws iam create-role --role-name cp-$ENV-task \
  --assume-role-policy-document file://trust-ecs.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam put-role-policy --role-name cp-$ENV-task --policy-name worker \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:$AWS_REGION:$ACCOUNT_ID:secret:cp/$ENV/*\"},
    {\"Effect\":\"Allow\",\"Action\":[\"logs:PutLogEvents\",\"logs:CreateLogStream\",\"cloudwatch:PutMetricData\"],\"Resource\":\"*\"}]}"
```

Two roles is not ceremony — the exec role belongs to the ECS agent, the task role to your code.
Collapsing them hands the container image-pull rights it never needs.

IAM is global (no `--region`) and eventually consistent: a role created seconds ago can fail the next
call. Retry once.

---

## 6. ElastiCache Redis

Cluster mode stays **disabled** — Streams, `BLPOP` and multi-key division locks assume one keyspace.

```bash
# subnet group — the same two subnets the tasks use, so both land in the same AZs
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name cp-$ENV-redis-subnets \
  --cache-subnet-group-description "Dispatch queue subnets" \
  --subnet-ids $SUBNET_A $SUBNET_B

# parameter group — the queue must never evict
aws elasticache create-cache-parameter-group \
  --cache-parameter-group-name cp-$ENV-redis7 \
  --cache-parameter-group-family redis7 \
  --description "noeviction - dispatch queue must not lose entries"

aws elasticache modify-cache-parameter-group \
  --cache-parameter-group-name cp-$ENV-redis7 \
  --parameter-name-values "ParameterName=maxmemory-policy,ParameterValue=noeviction"
```

`noeviction` makes a full cache fail writes loudly instead of silently dropping the oldest entries — a
dropped stream entry is a job that never gets dispatched.

```bash
aws elasticache create-replication-group \
  --replication-group-id cp-$ENV-dispatch-redis \
  --replication-group-description "Auto-Dispatch queue (Redis Streams)" \
  --engine redis --engine-version 7.1 \
  --cache-node-type cache.t4g.small \
  --num-cache-clusters 1 \
  --cache-subnet-group-name cp-$ENV-redis-subnets \
  --cache-parameter-group-name cp-$ENV-redis7 \
  --security-group-ids $REDIS_SG_ID \
  --transit-encryption-enabled --transit-encryption-mode required \
  --at-rest-encryption-enabled \
  --auth-token "$REDIS_AUTH_TOKEN" \
  --snapshot-retention-limit 7 \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

Want failover: replace `--num-cache-clusters 1` with
`--num-cache-clusters 2 --automatic-failover-enabled --multi-az-enabled`. Doubles the bill
(~$23 → ~$47/mo).

Takes 5–10 min. Then capture the endpoint — §7's task definition needs it:

```bash
aws elasticache wait replication-group-available --replication-group-id cp-$ENV-dispatch-redis

export REDIS_ENDPOINT=$(aws elasticache describe-replication-groups \
  --replication-group-id cp-$ENV-dispatch-redis \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' --output text)
echo $REDIS_ENDPOINT     # add to vars.sh
```

There is no public endpoint — the only thing that can reach it is a task in `$WORKER_SG_ID`. To poke
at it by hand, `aws ecs execute-command` into a running task (§10) and use `redis-cli` from there:
`redis-cli -h $REDIS_ENDPOINT -p 6379 --tls -a "$REDIS_AUTH_TOKEN" PING` → `PONG`.

---

## 7. ECR + ECS

### Registry

```bash
aws ecr create-repository --repository-name cp/dispatch-worker \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE \
  --tags Key=Project,Value=stream1 Key=ManagedBy,Value=techjays

# keep only the 10 most recent images
aws ecr put-lifecycle-policy --repository-name cp/dispatch-worker --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"description":"keep 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'
```

One repo for all environments — separate by tag (`prod-0.1.0`, `dev-0.1.0`), not by repo. `IMMUTABLE`
means a rollback to `prod-0.1.0` gets the same bytes it got last week.

### First image, from your laptop

CD (§9) takes over after this — but the service needs one image to exist before it can start.

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build --platform linux/amd64 -t $ECR_URI:$ENV-0.1.0 .
docker push $ECR_URI:$ENV-0.1.0
```

`--platform linux/amd64` is mandatory on Apple Silicon — without it the task dies with
`exec format error`. Login expires every 12 h; `no basic auth credentials` means re-run it.

### Log group

A task with nowhere to log fails to start, so this comes before the cluster.

```bash
aws logs create-log-group --log-group-name /ecs/cp-$ENV-dispatch-worker
aws logs put-retention-policy --log-group-name /ecs/cp-$ENV-dispatch-worker --retention-in-days 30
```

### Cluster

```bash
aws ecs create-cluster --cluster-name cp-$ENV-dispatch \
  --settings name=containerInsights,value=enabled \
  --tags key=Project,value=stream1 key=Env,value=$ENV key=ManagedBy,value=techjays
```

Note the lowercase `key=`/`value=` — the ECS API differs from EC2's `Key=`/`Value=` here.

### Task definition

`taskdef.json` — hand-edit `ACCOUNT`, `REGION`, `ENV`, the image tag and `REDIS_HOST`. CD re-renders
this file on every deploy, so commit it to the worker repo.

```json
{
  "family": "cp-ENV-dispatch-worker",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "runtimePlatform": { "cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX" },
  "executionRoleArn": "arn:aws:iam::ACCOUNT:role/cp-ENV-task-exec",
  "taskRoleArn": "arn:aws:iam::ACCOUNT:role/cp-ENV-task",
  "containerDefinitions": [{
    "name": "dispatch-worker",
    "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/cp/dispatch-worker:ENV-0.1.0",
    "essential": true,
    "environment": [
      { "name": "ENVIRONMENT",     "value": "ENV" },
      { "name": "REDIS_HOST",      "value": "cp-ENV-dispatch-redis.xxxx.ng.0001.use1.cache.amazonaws.com" },
      { "name": "REDIS_PORT",      "value": "6379" },
      { "name": "REDIS_TLS",       "value": "true" },
      { "name": "DISPATCH_STREAM", "value": "dispatch:stream" },
      { "name": "CONSUMER_GROUP",  "value": "dispatch-workers" },
      { "name": "MAX_CONCURRENT_DISPATCHES", "value": "20" }
    ],
    "secrets": [
      { "name": "REDIS_AUTH_TOKEN", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/redis-auth-token" }
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
  }]
}
```

```bash
aws ecs register-task-definition --cli-input-json file://taskdef.json
```

`REDIS_HOST` + `REDIS_TLS` + the injected `REDIS_AUTH_TOKEN` are the whole ECS↔Redis connection. The
client must speak TLS (`redis.asyncio` needs `ssl=True`); a plaintext client just times out.

`stopTimeout: 60` gives an in-flight dispatch time to `XACK` and release its division lock before
SIGKILL. Fargate accepts only valid CPU/memory pairs — `512` CPU takes 1–4 GB, `1024` takes 2–8 GB.

### Service — created at zero

```bash
aws ecs create-service \
  --cluster cp-$ENV-dispatch \
  --service-name cp-$ENV-dispatch-workers \
  --task-definition cp-$ENV-dispatch-worker \
  --desired-count 0 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$WORKER_SG_ID],assignPublicIp=ENABLED}" \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=0" \
  --enable-execute-command \
  --tags key=Project,value=stream1 key=Env,value=$ENV key=ManagedBy,value=techjays
```

- `--desired-count 0` — the Auto-Dispatch toggle turns workers on, not the deploy. A broken image
  costs nothing.
- `assignPublicIp=ENABLED` — required in a gateway-routed subnet. Safe here only because the worker SG
  has zero inbound rules. Flip to `DISABLED` the moment you move behind a NAT.
- `minimumHealthyPercent=0` — a queue consumer has no availability requirement during deploys.
- `deploymentCircuitBreaker` — a crash-looping image rolls back instead of retrying forever.
- No load balancer, no health check. `runningCount` and queue depth are the liveness signals.

---

## 8. Turn it on

```bash
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 1
aws ecs wait services-stable --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers

aws logs tail /ecs/cp-$ENV-dispatch-worker --since 10m --follow
```

Off again: `--desired-count 0`. There is no autoscaling policy — the toggle is the only scaling signal.

---

## 9. CD — GitHub push → ECR → ECS

Keyless, via OIDC. No AWS secrets stored in GitHub.

### One-time: trust GitHub

```bash
# skip if the account already has this provider
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

`trust-github.json` — replace `ACCOUNT` and `ORG/REPO`; `sub` scopes the role to one repo and one
branch:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::ACCOUNT:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:ORG/REPO:ref:refs/heads/main" }
    }
  }]
}
```

```bash
aws iam create-role --role-name cp-$ENV-github-deploy \
  --assume-role-policy-document file://trust-github.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam put-role-policy --role-name cp-$ENV-github-deploy --policy-name deploy \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":\"ecr:GetAuthorizationToken\",\"Resource\":\"*\"},
    {\"Effect\":\"Allow\",\"Action\":[\"ecr:BatchGetImage\",\"ecr:BatchCheckLayerAvailability\",\"ecr:CompleteLayerUpload\",\"ecr:InitiateLayerUpload\",\"ecr:PutImage\",\"ecr:UploadLayerPart\"],\"Resource\":\"arn:aws:ecr:$AWS_REGION:$ACCOUNT_ID:repository/cp/dispatch-worker\"},
    {\"Effect\":\"Allow\",\"Action\":[\"ecs:RegisterTaskDefinition\",\"ecs:DescribeTaskDefinition\"],\"Resource\":\"*\"},
    {\"Effect\":\"Allow\",\"Action\":[\"ecs:UpdateService\",\"ecs:DescribeServices\"],\"Resource\":\"arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:service/cp-$ENV-dispatch/cp-$ENV-dispatch-workers\"},
    {\"Effect\":\"Allow\",\"Action\":\"iam:PassRole\",\"Resource\":[\"arn:aws:iam::$ACCOUNT_ID:role/cp-$ENV-task-exec\",\"arn:aws:iam::$ACCOUNT_ID:role/cp-$ENV-task\"]}]}"
```

`iam:PassRole` is the one people forget — without it `RegisterTaskDefinition` fails with an opaque
`AccessDenied` on roles the workflow never names directly.

### The workflow

`.github/workflows/deploy.yml` in the worker repo, alongside the `taskdef.json` from §7:

```yaml
name: deploy
on:
  push:
    branches: [main]

permissions:
  id-token: write      # required for OIDC
  contents: read

env:
  AWS_REGION: us-east-1
  ECR_REPO: cp/dispatch-worker
  CLUSTER: cp-prod-dispatch
  SERVICE: cp-prod-dispatch-workers
  CONTAINER: dispatch-worker

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/cp-prod-github-deploy
          aws-region: ${{ env.AWS_REGION }}

      - id: ecr
        uses: aws-actions/amazon-ecr-login@v2

      - id: build
        env:
          REGISTRY: ${{ steps.ecr.outputs.registry }}
          TAG: prod-${{ github.sha }}
        run: |
          docker build --platform linux/amd64 -t $REGISTRY/$ECR_REPO:$TAG .
          docker push $REGISTRY/$ECR_REPO:$TAG
          echo "image=$REGISTRY/$ECR_REPO:$TAG" >> $GITHUB_OUTPUT

      - id: taskdef
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: taskdef.json
          container-name: ${{ env.CONTAINER }}
          image: ${{ steps.build.outputs.image }}

      - uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.taskdef.outputs.task-definition }}
          service: ${{ env.SERVICE }}
          cluster: ${{ env.CLUSTER }}
          wait-for-service-stability: true
```

The commit SHA is the image tag — immutable, and rollback is redeploying an older SHA.
`render-task-definition` swaps only the image line, so every other field stays under review in git.

With `desired-count 0` the deploy still succeeds — zero running tasks is a stable service. The new
revision starts being used the next time the toggle scales to 1.

---

## 10. Verify

```bash
# service state
aws ecs describe-services --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers \
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount,TaskDef:taskDefinition}' --output table

# redis: encrypted, auth on, not evicting
aws elasticache describe-replication-groups --replication-group-id cp-$ENV-dispatch-redis \
  --query 'ReplicationGroups[0].{Status:Status,TLS:TransitEncryptionEnabled,Auth:AuthTokenEnabled}' --output table
aws elasticache describe-cache-parameters --cache-parameter-group-name cp-$ENV-redis7 \
  --query 'Parameters[?ParameterName==`maxmemory-policy`].ParameterValue' --output text   # noeviction

# shell into a running task
aws ecs list-tasks --cluster cp-$ENV-dispatch --service-name cp-$ENV-dispatch-workers --query 'taskArns' --output text
aws ecs execute-command --cluster cp-$ENV-dispatch --task <task-arn> \
  --container dispatch-worker --interactive --command "/bin/sh"
```

Task stuck in `PENDING`? Read `stoppedReason`:

```bash
aws ecs describe-tasks --cluster cp-$ENV-dispatch --tasks <task-arn> \
  --query 'tasks[0].{Status:lastStatus,Reason:stoppedReason}' --output json
```

| `stoppedReason` | Cause |
|---|---|
| `CannotPullContainerError` | no egress — missing IGW route (§2) or `assignPublicIp=DISABLED` |
| `ResourceInitializationError: ... secretsmanager` | exec-role policy or wrong secret ARN — §4, §5 |
| `exec format error` | ARM image on an X86_64 task — rebuild with `--platform linux/amd64` |
| task starts, then times out on Redis | §3 rule missing, or the client isn't using TLS |

---

## Cost

| Item | Monthly |
|---|---|
| ElastiCache `cache.t4g.small`, always on | ~$23 (×2 with failover ⇒ ~$47) |
| Fargate, 2 tasks × 8 h/day at 1 vCPU / 2 GB | ~$24 — **$0** when toggled off |
| VPC, subnets, internet gateway | $0 |
| ECR storage, CloudWatch logs | a few dollars |

Fixed floor ≈ **$23/mo** — Redis, because the queue must survive between dispatches. Everything else
scales to zero. Adding a NAT gateway later adds ~$32/mo before any traffic.

---

## Teardown

Reverse order. Everything here is new, so nothing survives.

```bash
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 0
aws ecs delete-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --force
aws ecs delete-cluster --cluster cp-$ENV-dispatch
aws elasticache delete-replication-group --replication-group-id cp-$ENV-dispatch-redis
aws elasticache wait replication-group-deleted --replication-group-id cp-$ENV-dispatch-redis
aws elasticache delete-cache-subnet-group --cache-subnet-group-name cp-$ENV-redis-subnets
aws ecr delete-repository --repository-name cp/dispatch-worker --force
aws logs delete-log-group --log-group-name /ecs/cp-$ENV-dispatch-worker
aws secretsmanager delete-secret --secret-id cp/$ENV/redis-auth-token --force-delete-without-recovery

aws ec2 delete-security-group --group-id $REDIS_SG_ID
aws ec2 delete-security-group --group-id $WORKER_SG_ID
aws ec2 detach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID
aws ec2 delete-internet-gateway --internet-gateway-id $IGW_ID
aws ec2 delete-subnet --subnet-id $SUBNET_A
aws ec2 delete-subnet --subnet-id $SUBNET_B
aws ec2 delete-route-table --route-table-id $RTB_ID
aws ec2 delete-vpc --vpc-id $VPC_ID
```

Delete the roles too — they cost nothing but they accumulate:

```bash
for R in cp-$ENV-task-exec cp-$ENV-task cp-$ENV-github-deploy; do
  for P in $(aws iam list-role-policies --role-name $R --query 'PolicyNames' --output text); do
    aws iam delete-role-policy --role-name $R --policy-name $P
  done
  for A in $(aws iam list-attached-role-policies --role-name $R --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name $R --policy-arn $A
  done
  aws iam delete-role --role-name $R
done
```

Find anything this doc created, at any time:

```bash
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=stream1 \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
```
