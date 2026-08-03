# 02 · Networking — security groups + egress

**Status:** NEW (2 security groups) · **Cloud:** AWS · **Used by:** UC-A

No new VPC, no new subnets. The new tiers go into the **existing FieldJetX VPC** so that
worker↔broker and worker↔SQL Server traffic never leaves it. What is new is the traffic rules.

Target from §4: *neither ElastiCache nor SQL Server exposes a public IP; the only public entry point
is the .NET API behind the load balancer.*

---

## Prereqs

`vars.sh` / `vars.ps1` from `01` loaded — `VPC_ID`, `SUBNET_A`, `SUBNET_B`, `EC2_SG_ID`, `SQL_SG_ID`.

---

## Steps

### 1. Security group for the dispatch workers (ECS Fargate tasks)

```bash
export WORKER_SG_ID=$(aws ec2 create-security-group \
  --group-name cp-$ENV-dispatch-workers \
  --description "Stream 1 Auto-Dispatch Fargate workers" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=UseCase,Value=A},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' \
  --query 'GroupId' --output text)
echo $WORKER_SG_ID
```

Fargate tasks need **no inbound rules at all** — nothing calls them; they pull work from Redis.
The default egress-all rule stays (they must reach SNS, ECR, CloudWatch over HTTPS).

### 2. Security group for ElastiCache

```bash
export REDIS_SG_ID=$(aws ec2 create-security-group \
  --group-name cp-$ENV-dispatch-redis \
  --description "Stream 1 dispatch queue - ElastiCache for Redis" \
  --vpc-id $VPC_ID \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=stream1},{Key=UseCase,Value=A},{Key=Env,Value=prod},{Key=ManagedBy,Value=techjays}]' \
  --query 'GroupId' --output text)
```

### 3. Allow Redis 6379 from the workers and from the .NET host

Both sides write to Redis: the .NET API `XADD`s the dispatch and `LPUSH`es technician replies; the
worker consumes with `XREADGROUP` and blocks on `BLPOP`.

```bash
# workers -> redis
aws ec2 authorize-security-group-ingress --group-id $REDIS_SG_ID \
  --protocol tcp --port 6379 --source-group $WORKER_SG_ID

# .NET host on EC2 -> redis
aws ec2 authorize-security-group-ingress --group-id $REDIS_SG_ID \
  --protocol tcp --port 6379 --source-group $EC2_SG_ID
```

### 4. Allow SQL Server 1433 from the workers

The worker writes the assignment to the system of record. **This edits an existing security group** —
one rule, no removals.

```bash
aws ec2 authorize-security-group-ingress --group-id $SQL_SG_ID \
  --protocol tcp --port 1433 --source-group $WORKER_SG_ID
```

### 5. Egress path for the tasks — pick one

Fargate tasks in a **private** subnet still need outbound HTTPS to pull the image from ECR, fetch
secrets, publish to SNS, and ship logs. Two ways:

**A — reuse the existing NAT gateway (recommended).** If `01` found a NAT gateway and the private
subnets route `0.0.0.0/0` to it, you are done — nothing to create. Verify:

```bash
aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=$SUBNET_A \
  --query 'RouteTables[].Routes[?DestinationCidrBlock==`0.0.0.0/0`]' --output json
```

Expect a `NatGatewayId`. Cost: already paid by the existing platform.

**B — interface VPC endpoints (only if there is no NAT).** Needed: `ecr.api`, `ecr.dkr`, `logs`,
`secretsmanager`, `sns`, plus the free `s3` **gateway** endpoint for image layers.

```bash
for SVC in ecr.api ecr.dkr logs secretsmanager sns; do
  aws ec2 create-vpc-endpoint --vpc-id $VPC_ID --vpc-endpoint-type Interface \
    --service-name com.amazonaws.$AWS_REGION.$SVC \
    --subnet-ids $SUBNET_A $SUBNET_B \
    --security-group-ids $REDIS_SG_ID \
    --private-dns-enabled
done

aws ec2 create-vpc-endpoint --vpc-id $VPC_ID --vpc-endpoint-type Gateway \
  --service-name com.amazonaws.$AWS_REGION.s3 --route-table-ids <rtb-xxxx>
```

> **Cost warning.** Interface endpoints bill ≈ $7.30/mo **each, per AZ**. Five endpoints × 2 AZ
> ≈ $73/mo — more than the entire rest of the new AWS tier (§10 floor ≈ $23/mo). Take option A
> unless the account genuinely has no NAT. The endpoint SG must allow inbound 443 from
> `$WORKER_SG_ID` if you go this route.

**Never** set `assignPublicIp=ENABLED` on the ECS service to dodge this. It puts the worker on the
public internet and breaks the §4 network model.

---

## Verify

```bash
# both new SGs exist
aws ec2 describe-security-groups --group-ids $REDIS_SG_ID $WORKER_SG_ID \
  --query 'SecurityGroups[].{Name:GroupName,Id:GroupId,In:length(IpPermissions)}' --output table

# the 1433 rule landed on the SQL SG
aws ec2 describe-security-groups --group-ids $SQL_SG_ID \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`1433`].UserIdGroupPairs[].GroupId' --output text
```

Append `REDIS_SG_ID` and `WORKER_SG_ID` to `vars.sh`.

---

## Talks to

| From | To | Port | Why |
|---|---|---|---|
| ECS worker (`$WORKER_SG_ID`) | ElastiCache (`$REDIS_SG_ID`) | 6379/TLS | `XREADGROUP`, `XACK`, `BLPOP`, division lock |
| ECS worker | RDS SQL Server (`$SQL_SG_ID`) | 1433 | write assignment |
| ECS worker | SNS / ECR / Logs / Secrets | 443 out | push, image pull, logs, secrets |
| .NET on EC2 (`$EC2_SG_ID`) | ElastiCache | 6379/TLS | `XADD` dispatch, `LPUSH` reply, `SETNX resp:done` |

Full map with auth per hop: [`11-service-communication.md`](11-service-communication.md).

---

## Gotchas

- SG rules reference **groups, not CIDRs** — keeps working if subnets change.
- ElastiCache and Fargate must sit in the **same AZs**; pick `SUBNET_A`/`SUBNET_B` once and reuse them
  in `05` and `07`.
- Don't open 6379 to the VPC CIDR. Only two source groups need it.
- If Fargate tasks hang in `PENDING` with an ECR timeout, the egress path (step 5) is the cause.

**Next:** [`03-iam.md`](03-iam.md)
