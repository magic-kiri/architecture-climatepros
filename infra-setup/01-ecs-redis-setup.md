# 01 · ECS Fargate + ElastiCache Redis

**Prereq:** [`00-aws-cli-setup.md`](00-aws-cli-setup.md) done — `aws sts get-caller-identity` works.

**Standalone.** Own VPC, nothing discovered, nothing existing touched. One pass, top to bottom:

```
CD pipeline ──► ECR ──► ECS service ──► task ──► ElastiCache Redis (6379 TLS)
(see 02)                (Fargate)
```

| Built here | Name |
|---|---|
| VPC + 2 subnets + internet gateway | `cp-prod-vpc` |
| Security groups (2) | `cp-prod-workers`, `cp-prod-redis` |
| Secret (1) | `cp/prod/redis-auth-token` |
| IAM roles (2) | task-exec, task |
| ElastiCache Redis | `cp-prod-dispatch-redis` |
| ECR repo | `cp/dispatch-worker` |
| ECS cluster / task def / service | `cp-prod-dispatch` |

CD (build → ECR → ECS deploy, GitHub Actions or Azure DevOps) is a separate doc — see
[`02-cicd-setup.md`](02-cicd-setup.md). Everything above is new and deletable — see
[`03-teardown.md`](03-teardown.md) to remove it. Connecting to the existing FieldJetX VPC and SQL
Server is a later step, not this one.

**Platforms.** Every command block below is given twice — **macOS / Linux** (bash) first, then
**Windows (PowerShell 7+, or Windows PowerShell 5.1)**. All IAM policy documents are passed
`file://...json` rather than inline, so there is no bash-vs-PowerShell quoting difference to trip over —
see `00` § "Cross-platform rules". Once you `aws ecs execute-command` into a running task (§9), you're
in the container's own Linux `/bin/sh` regardless of which OS you ran the `aws` command from — those
in-container lines are not duplicated. Same for §7 "First image" — it runs in **AWS CloudShell**
(always bash, no local Docker required), so that block isn't duplicated either.

---

## 1. Variables

Nothing to discover. Same variables, two files — pick the one for your shell. Both live **outside git**.

**macOS / Linux** — save as `vars.sh`, `source vars.sh` to load, re-source in every new terminal:

```bash
export AWS_PROFILE="cp-test"
export AWS_REGION="us-east-1"
export ENV="prod"
export ACCOUNT_ID="123456789012"   # replace with: aws sts get-caller-identity --profile cp-test --query Account --output text

# filled in as you go
export VPC_ID=""
export SUBNET_A=""
export SUBNET_B=""
export WORKER_SG_ID=""
export REDIS_SG_ID=""
export REDIS_ENDPOINT=""
export ECR_URI="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cp/dispatch-worker"
```

**Windows (PowerShell)** — save as `vars.ps1`, `. C:\path\to\vars.ps1` to load, re-source in every new terminal:

```powershell
$env:AWS_PROFILE = "cp-test"
$env:AWS_REGION  = "us-east-1"
$env:ENV         = "prod"
$env:ACCOUNT_ID  = "123456789012"   # replace with: aws sts get-caller-identity --profile cp-test --query Account --output text

# filled in as you go
$env:VPC_ID        = ""
$env:SUBNET_A      = ""
$env:SUBNET_B      = ""
$env:WORKER_SG_ID  = ""
$env:REDIS_SG_ID   = ""
$env:REDIS_ENDPOINT= ""
$env:ECR_URI       = "$env:ACCOUNT_ID.dkr.ecr.$env:AWS_REGION.amazonaws.com/cp/dispatch-worker"
```

Tag every resource `Project=stream1 Env=$ENV ManagedBy=techjays` — teardown and cost attribution
depend on it. The commands below already do.

---

## 2. Network

A `/16` with two `/24` subnets in different AZs — ElastiCache requires two AZs, and Fargate wants the
same two.

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
$env:VPC_ID = $(aws ec2 create-vpc --cidr-block 10.42.0.0/16 `
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=cp-prod-vpc},{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' `
  --query 'Vpc.VpcId' --output text)

# ElastiCache endpoints resolve by DNS name — this must be on
aws ec2 modify-vpc-attribute --vpc-id $env:VPC_ID --enable-dns-hostnames

$env:SUBNET_A = $(aws ec2 create-subnet --vpc-id $env:VPC_ID --cidr-block 10.42.1.0/24 `
  --availability-zone "$($env:AWS_REGION)a" `
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cp-prod-a},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' `
  --query 'Subnet.SubnetId' --output text)

$env:SUBNET_B = $(aws ec2 create-subnet --vpc-id $env:VPC_ID --cidr-block 10.42.2.0/24 `
  --availability-zone "$($env:AWS_REGION)b" `
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cp-prod-b},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' `
  --query 'Subnet.SubnetId' --output text)
```

Tasks need outbound 443 to pull the image, read the secret and ship logs. An internet gateway does
that for free; a NAT gateway costs ~$32/mo. Use the gateway:

**macOS / Linux**

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

# verify before moving on — must show the 0.0.0.0/0 route AND both subnet IDs
aws ec2 describe-route-tables --route-table-ids $RTB_ID \
  --query 'RouteTables[0].{Routes:Routes[].DestinationCidrBlock,Associations:Associations[].SubnetId}'
```

**Windows (PowerShell)**

```powershell
$env:IGW_ID = $(aws ec2 create-internet-gateway `
  --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=cp-prod-igw},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' `
  --query 'InternetGateway.InternetGatewayId' --output text)

aws ec2 attach-internet-gateway --vpc-id $env:VPC_ID --internet-gateway-id $env:IGW_ID

$env:RTB_ID = $(aws ec2 create-route-table --vpc-id $env:VPC_ID `
  --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=cp-prod-rtb},{Key=Project,Value=stream1},{Key=Env,Value=prod}]' `
  --query 'RouteTable.RouteTableId' --output text)

aws ec2 create-route --route-table-id $env:RTB_ID --destination-cidr-block 0.0.0.0/0 --gateway-id $env:IGW_ID
aws ec2 associate-route-table --route-table-id $env:RTB_ID --subnet-id $env:SUBNET_A
aws ec2 associate-route-table --route-table-id $env:RTB_ID --subnet-id $env:SUBNET_B

# verify before moving on — must show the 0.0.0.0/0 route AND both subnet IDs
aws ec2 describe-route-tables --route-table-ids $env:RTB_ID `
  --query 'RouteTables[0].{Routes:Routes[].DestinationCidrBlock,Associations:Associations[].SubnetId}'
```

An empty `Routes`/`Associations` result here means `create-route` or `associate-route-table` ran
against a blank `$IGW_ID`/`$SUBNET_A`/`$SUBNET_B` (usually because those variables came from a
different terminal session that already lost its in-memory values) and silently no-op'd rather than
erroring. Don't proceed to §3 until this check passes — otherwise the task will launch, sit in
`pending`, and only fail ~15 minutes later when it can't reach Secrets Manager (no route out of the
subnet at all).

Add `VPC_ID`, `SUBNET_A`, `SUBNET_B`, `IGW_ID`, `RTB_ID` to your vars file.

The tasks get a public IP (§7) so they can reach the gateway — but their security group has **no
inbound rules**, so nothing can reach them. Redis never gets a public IP at all. To move to private
subnets + NAT later, swap the route target and set `assignPublicIp=DISABLED`; nothing else changes.

---

## 3. Security groups

Two groups, one rule.

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
# tasks — no inbound at all; nothing calls them, they pull work from Redis
$env:WORKER_SG_ID = $(aws ec2 create-security-group `
  --group-name "cp-$env:ENV-workers" --description "Dispatch Fargate workers" --vpc-id $env:VPC_ID `
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' `
  --query 'GroupId' --output text)

$env:REDIS_SG_ID = $(aws ec2 create-security-group `
  --group-name "cp-$env:ENV-redis" --description "Dispatch queue - ElastiCache" --vpc-id $env:VPC_ID `
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' `
  --query 'GroupId' --output text)

# workers -> redis
aws ec2 authorize-security-group-ingress --group-id $env:REDIS_SG_ID `
  --protocol tcp --port 6379 --source-group $env:WORKER_SG_ID
```

Rules reference **groups, not CIDRs** — they survive subnet changes. Default egress-all stays on the
worker group; that is the 443 the task needs.

**Public debugging (optional, insecure) — opens every port on the worker SG to the whole internet.**
Only for temporary hands-on debugging against a task with a public IP. The whole point of §2/§3 up to
now was zero inbound rules on this group — this rule removes that protection entirely, for every port,
for anyone on the internet, not just you. Revoke it the moment you're done
(`aws ec2 revoke-security-group-ingress` with the same arguments), and never leave it on past a test
session.

**macOS / Linux**

```bash
# Allow all inbound traffic to workers from anywhere (test — for public debugging)
aws ec2 authorize-security-group-ingress --group-id $WORKER_SG_ID \
  --protocol -1 --cidr 0.0.0.0/0 --profile cp-test
```

**Windows (PowerShell)**

```powershell
# Allow all inbound traffic to workers from anywhere (test — for public debugging)
aws ec2 authorize-security-group-ingress --group-id $env:WORKER_SG_ID `
  --protocol -1 --cidr 0.0.0.0/0 --profile cp-test
```

Append both IDs to your vars file.

---

## 4. Secret — the Redis auth token

Generate once. The token cannot be changed later without a rotation call, and cannot contain `/ " @`
or spaces.

**macOS / Linux**

```bash
export REDIS_AUTH_TOKEN=$(openssl rand -hex 32)

aws secretsmanager create-secret --name cp/$ENV/redis-auth-token \
  --secret-string "$REDIS_AUTH_TOKEN" \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays \
  --query 'ARN' --output text
```

**Windows (PowerShell)** — no `openssl` on a stock Windows box, so generate the 32 random bytes
natively and hex-encode them (same output shape as `openssl rand -hex 32`):

```powershell
$env:REDIS_AUTH_TOKEN = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })

aws secretsmanager create-secret --name "cp/$env:ENV/redis-auth-token" `
  --secret-string $env:REDIS_AUTH_TOKEN `
  --tags "Key=Project,Value=stream1" "Key=Env,Value=$env:ENV" "Key=ManagedBy,Value=techjays" `
  --query 'ARN' --output text
```

Keep `REDIS_AUTH_TOKEN` in the shell — §6 needs it at creation time. It is **not** in your vars file.

---

## 5. IAM — two task roles

`trust-ecs.json` (same file, either OS):

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

`read-secrets-policy.json` — hand-edit `REGION`/`ACCOUNT`/`ENV` (same treatment as `taskdef.json` in §7):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/*"
  }]
}
```

**macOS / Linux**

```bash
aws iam create-role --role-name cp-$ENV-task-exec \
  --assume-role-policy-document file://trust-ecs.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam attach-role-policy --role-name cp-$ENV-task-exec \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy --role-name cp-$ENV-task-exec --policy-name read-secrets \
  --policy-document file://read-secrets-policy.json
```

**Windows (PowerShell)**

```powershell
aws iam create-role --role-name "cp-$env:ENV-task-exec" `
  --assume-role-policy-document file://trust-ecs.json `
  --tags "Key=Project,Value=stream1" "Key=Env,Value=$env:ENV" "Key=ManagedBy,Value=techjays"

aws iam attach-role-policy --role-name "cp-$env:ENV-task-exec" `
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy --role-name "cp-$env:ENV-task-exec" --policy-name read-secrets `
  --policy-document file://read-secrets-policy.json
```

**Task role** — used *by* the worker process at runtime.

`worker-policy.json` — hand-edit `REGION`/`ACCOUNT`/`ENV`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:cp/ENV/*" },
    { "Effect": "Allow", "Action": ["logs:PutLogEvents", "logs:CreateLogStream", "cloudwatch:PutMetricData"], "Resource": "*" }
  ]
}
```

**macOS / Linux**

```bash
aws iam create-role --role-name cp-$ENV-task \
  --assume-role-policy-document file://trust-ecs.json \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam put-role-policy --role-name cp-$ENV-task --policy-name worker \
  --policy-document file://worker-policy.json
```

**Windows (PowerShell)**

```powershell
aws iam create-role --role-name "cp-$env:ENV-task" `
  --assume-role-policy-document file://trust-ecs.json `
  --tags "Key=Project,Value=stream1" "Key=Env,Value=$env:ENV" "Key=ManagedBy,Value=techjays"

aws iam put-role-policy --role-name "cp-$env:ENV-task" --policy-name worker `
  --policy-document file://worker-policy.json
```

Two roles is not ceremony — the exec role belongs to the ECS agent, the task role to your code.
Collapsing them hands the container image-pull rights it never needs.

IAM is global (no `--region`) and eventually consistent: a role created seconds ago can fail the next
call. Retry once.

---

## 6. ElastiCache Redis

Cluster mode stays **disabled** — Streams, `BLPOP` and multi-key division locks assume one keyspace.

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
# subnet group — the same two subnets the tasks use, so both land in the same AZs
aws elasticache create-cache-subnet-group `
  --cache-subnet-group-name "cp-$env:ENV-redis-subnets" `
  --cache-subnet-group-description "Dispatch queue subnets" `
  --subnet-ids $env:SUBNET_A $env:SUBNET_B

# parameter group — the queue must never evict
aws elasticache create-cache-parameter-group `
  --cache-parameter-group-name "cp-$env:ENV-redis7" `
  --cache-parameter-group-family redis7 `
  --description "noeviction - dispatch queue must not lose entries"

aws elasticache modify-cache-parameter-group `
  --cache-parameter-group-name "cp-$env:ENV-redis7" `
  --parameter-name-values "ParameterName=maxmemory-policy,ParameterValue=noeviction"
```

`noeviction` makes a full cache fail writes loudly instead of silently dropping the oldest entries — a
dropped stream entry is a job that never gets dispatched.

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
aws elasticache create-replication-group `
  --replication-group-id "cp-$env:ENV-dispatch-redis" `
  --replication-group-description "Auto-Dispatch queue (Redis Streams)" `
  --engine redis --engine-version 7.1 `
  --cache-node-type cache.t4g.small `
  --num-cache-clusters 1 `
  --cache-subnet-group-name "cp-$env:ENV-redis-subnets" `
  --cache-parameter-group-name "cp-$env:ENV-redis7" `
  --security-group-ids $env:REDIS_SG_ID `
  --transit-encryption-enabled --transit-encryption-mode required `
  --at-rest-encryption-enabled `
  --auth-token $env:REDIS_AUTH_TOKEN `
  --snapshot-retention-limit 7 `
  --tags "Key=Project,Value=stream1" "Key=Env,Value=$env:ENV" "Key=ManagedBy,Value=techjays"
```

Want failover: replace `--num-cache-clusters 1` with
`--num-cache-clusters 2 --automatic-failover-enabled --multi-az-enabled`. Doubles the bill
(~$23 → ~$47/mo).

Takes 5–10 min. Then capture the endpoint — §7's task definition needs it:

**macOS / Linux**

```bash
aws elasticache wait replication-group-available --replication-group-id cp-$ENV-dispatch-redis

export REDIS_ENDPOINT=$(aws elasticache describe-replication-groups \
  --replication-group-id cp-$ENV-dispatch-redis \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' --output text)
echo $REDIS_ENDPOINT     # add to vars.sh
```

**Windows (PowerShell)**

```powershell
aws elasticache wait replication-group-available --replication-group-id "cp-$env:ENV-dispatch-redis"

$env:REDIS_ENDPOINT = $(aws elasticache describe-replication-groups `
  --replication-group-id "cp-$env:ENV-dispatch-redis" `
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' --output text)
Write-Host $env:REDIS_ENDPOINT     # add to vars.ps1
```

There is no public endpoint — the only thing that can reach it is a task in `$WORKER_SG_ID`. To poke
at it by hand, `aws ecs execute-command` into a running task (§9) and use `redis-cli` from there —
this runs inside the container's own Linux shell, so it's the same command regardless of which OS you
ran the `aws` CLI from:

```
redis-cli -h $REDIS_ENDPOINT -p 6379 --tls -a "$REDIS_AUTH_TOKEN" PING   # → PONG
```

---

## 7. ECR + ECS

### Registry

Literal, no variables — identical either OS apart from the line-continuation character.

**macOS / Linux**

```bash
aws ecr create-repository --repository-name cp/dispatch-worker \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE \
  --tags Key=Project,Value=stream1 Key=ManagedBy,Value=techjays

# keep only the 10 most recent images
aws ecr put-lifecycle-policy --repository-name cp/dispatch-worker --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"description":"keep 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'
```

**Windows (PowerShell)**

```powershell
aws ecr create-repository --repository-name cp/dispatch-worker `
  --image-scanning-configuration scanOnPush=true `
  --image-tag-mutability IMMUTABLE `
  --tags Key=Project,Value=stream1 Key=ManagedBy,Value=techjays

# keep only the 10 most recent images
# Note: inline JSON breaks in PowerShell — write to file first, then reference with file://
[System.IO.File]::WriteAllText("$PWD\lifecycle.json", '{"rules":[{"rulePriority":1,"description":"keep 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}')
aws ecr put-lifecycle-policy --repository-name cp/dispatch-worker `
  --lifecycle-policy-text file://lifecycle.json
```

One repo for all environments — separate by tag (`prod-0.1.0`, `dev-0.1.0`), not by repo. `IMMUTABLE`
means a rollback to `prod-0.1.0` gets the same bytes it got last week.

### First image, via CloudShell (no local Docker needed)

CD (see `02-cicd-setup.md`) takes over after this — but the service needs one image to exist before it can start. No one on
the ClimatePros side needs Docker installed: the image is built once elsewhere and shipped as a `docker
save`d tarball (`dispatch-worker-amd64.tar.gz`); loading and pushing it happens in **AWS CloudShell**,
which has Docker preinstalled. This is bash-only regardless of your local OS, so there's no PowerShell
variant of this block.

1. AWS Console → CloudShell (`>_` icon, top nav) — open it under the account/profile this image is going to.
2. Actions → Upload file → pick `dispatch-worker-amd64.tar.gz`. It lands in `~`.
3. Load and push:

```bash
gunzip ~/dispatch-worker-amd64.tar.gz
docker load -i ~/dispatch-worker-amd64.tar
# note the "Loaded image: <name>:<tag>" line — that's the local tag to reference below (check `docker images` if unsure)

export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ENV=test   # match whichever environment this image is for

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker tag dispatch-worker:latest-amd64 $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cp/dispatch-worker:$ENV-0.1.0
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cp/dispatch-worker:$ENV-0.1.0
```

The ECR repo (previous subsection) must already exist — `docker push` doesn't create it. The `-amd64` in
the filename matters: Fargate here runs `X86_64` (see the task definition below), and an arm64 image
dies with `exec format error`. Login expires every 12 h; `no basic auth credentials` means re-run it.
CloudShell's home directory persists across sessions but nothing else does — safe to delete the tarball
once the push succeeds.

### Log group

A task with nowhere to log fails to start, so this comes before the cluster.

**macOS / Linux**

```bash
aws logs create-log-group --log-group-name /ecs/cp-$ENV-dispatch-worker
aws logs put-retention-policy --log-group-name /ecs/cp-$ENV-dispatch-worker --retention-in-days 30
```

**Windows (PowerShell)**

```powershell
aws logs create-log-group --log-group-name "/ecs/cp-$env:ENV-dispatch-worker"
aws logs put-retention-policy --log-group-name "/ecs/cp-$env:ENV-dispatch-worker" --retention-in-days 30
```

### Cluster

**macOS / Linux**

```bash
aws ecs create-cluster --cluster-name cp-$ENV-dispatch \
  --settings name=containerInsights,value=enabled \
  --tags key=Project,value=stream1 key=Env,value=$ENV key=ManagedBy,value=techjays
```

**Windows (PowerShell)**

```powershell
aws ecs create-cluster --cluster-name "cp-$env:ENV-dispatch" `
  --settings name=containerInsights,value=enabled `
  --tags "key=Project,value=stream1" "key=Env,value=$env:ENV" "key=ManagedBy,value=techjays"
```

Note the lowercase `key=`/`value=` — the ECS API differs from EC2's `Key=`/`Value=` here.

### Get the secret ARN

Needed for the task definition below. Secrets Manager appends a random 6-character suffix to every
ARN (`...redis-auth-token-AbCdEf`) — query it rather than typing the pattern by hand; ECS can fail to
resolve a secret referenced by a guessed/partial ARN.

**macOS / Linux**

```bash
export SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id cp/$ENV/redis-auth-token \
  --query ARN --output text)
echo "SECRET_ARN: $SECRET_ARN"
```

**Windows (PowerShell)**

```powershell
$env:SECRET_ARN = (aws secretsmanager describe-secret `
  --secret-id "cp/$env:ENV/redis-auth-token" `
  --query ARN --output text)
echo "SECRET_ARN: $env:SECRET_ARN"
```

### Task definition

`taskdef.json` — hand-edit `ACCOUNT`, `REGION`, `ENV`, the image tag, `REDIS_HOST`, and paste in the
exact `SECRET_ARN` from above (not the hand-typed pattern below — see previous step). CD re-renders
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
      { "name": "REDIS_AUTH_TOKEN", "valueFrom": "SECRET_ARN" }
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

Identical on both platforms — no variables involved, `file://` works the same everywhere:

```
aws ecs register-task-definition --cli-input-json file://taskdef.json
```

`REDIS_HOST` + `REDIS_TLS` + the injected `REDIS_AUTH_TOKEN` are the whole ECS↔Redis connection. The
client must speak TLS (`redis.asyncio` needs `ssl=True`); a plaintext client just times out.

`stopTimeout: 60` gives an in-flight dispatch time to `XACK` and release its division lock before
SIGKILL. Fargate accepts only valid CPU/memory pairs — `512` CPU takes 1–4 GB, `1024` takes 2–8 GB.

### Service — created at zero

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
aws ecs create-service `
  --cluster "cp-$env:ENV-dispatch" `
  --service-name "cp-$env:ENV-dispatch-workers" `
  --task-definition "cp-$env:ENV-dispatch-worker" `
  --desired-count 0 `
  --launch-type FARGATE `
  --network-configuration "awsvpcConfiguration={subnets=[$env:SUBNET_A,$env:SUBNET_B],securityGroups=[$env:WORKER_SG_ID],assignPublicIp=ENABLED}" `
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=0" `
  --enable-execute-command `
  --tags "key=Project,value=stream1" "key=Env,value=$env:ENV" "key=ManagedBy,value=techjays"
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

**macOS / Linux**

```bash
aws ecs update-service --cluster cp-$ENV-dispatch --service cp-$ENV-dispatch-workers --desired-count 1
aws ecs wait services-stable --cluster cp-$ENV-dispatch --services cp-$ENV-dispatch-workers

aws logs tail /ecs/cp-$ENV-dispatch-worker --since 10m --follow
```

**Windows (PowerShell)**

```powershell
aws ecs update-service --cluster "cp-$env:ENV-dispatch" --service "cp-$env:ENV-dispatch-workers" --desired-count 1
aws ecs wait services-stable --cluster "cp-$env:ENV-dispatch" --services "cp-$env:ENV-dispatch-workers"

aws logs tail "/ecs/cp-$env:ENV-dispatch-worker" --since 10m --follow
```

Off again: `--desired-count 0`. There is no autoscaling policy — the toggle is the only scaling signal.

---

## 9. Verify

**macOS / Linux**

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

**Windows (PowerShell)** — with explicit `--profile cp-test` example on the first line:

```powershell
# service state
aws ecs describe-services --cluster "cp-$env:ENV-dispatch" --services "cp-$env:ENV-dispatch-workers" --profile cp-test `
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount,TaskDef:taskDefinition}' --output table

# redis: encrypted, auth on, not evicting
aws elasticache describe-replication-groups --replication-group-id "cp-$env:ENV-dispatch-redis" `
  --query 'ReplicationGroups[0].{Status:Status,TLS:TransitEncryptionEnabled,Auth:AuthTokenEnabled}' --output table
aws elasticache describe-cache-parameters --cache-parameter-group-name "cp-$env:ENV-redis7" `
  --query 'Parameters[?ParameterName==`maxmemory-policy`].ParameterValue' --output text   # noeviction

# shell into a running task
aws ecs list-tasks --cluster "cp-$env:ENV-dispatch" --service-name "cp-$env:ENV-dispatch-workers" --query 'taskArns' --output text
aws ecs execute-command --cluster "cp-$env:ENV-dispatch" --task <task-arn> `
  --container dispatch-worker --interactive --command "/bin/sh"
```

Task stuck in `PENDING`? Read `stoppedReason`:

**macOS / Linux**

```bash
aws ecs describe-tasks --cluster cp-$ENV-dispatch --tasks <task-arn> \
  --query 'tasks[0].{Status:lastStatus,Reason:stoppedReason}' --output json
```

**Windows (PowerShell)**

```powershell
aws ecs describe-tasks --cluster "cp-$env:ENV-dispatch" --tasks <task-arn> `
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

Moved to its own file — see [`03-teardown.md`](03-teardown.md) §2 (core infra + roles) and §3
(verify nothing is left).
