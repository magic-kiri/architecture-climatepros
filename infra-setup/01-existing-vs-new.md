# 01 · Existing vs New — discover, then name

**Status:** prerequisite · **Creates nothing.** Read the existing ClimatePros infra out of the account
and record the IDs the later files depend on. Everything new is built **inside** the existing VPC.

---

## The two inventories

### Existing — reused as-is (discover, never create)

| Component | AWS service | What we need from it |
|---|---|---|
| .NET Legacy API + .NET Microservices API | **EC2** (one host) | instance id, subnet, security group, **instance role** |
| SQL Server — system of record | **RDS (SQL Server)** | endpoint, port 1433, security group |
| Network | **VPC**, subnets, route tables, **NAT gateway** | VPC id, private subnet ids, NAT presence + its public IP |
| Public entry point | **ALB / API Gateway + WAF** | confirm it exists — we add nothing here |
| Client apps | FieldJetX Flutter mobile + Angular web | no AWS resource |

### New — created by this runbook

| Component | AWS service | File |
|---|---|---|
| Dispatch queue (Redis Streams) | ElastiCache for Redis | `05` |
| Worker image registry | ECR | `06` |
| Dispatch workers, scale 0→1 | ECS Fargate | `07` |
| Push to technician phones | SNS (APNs + FCM) | `08` |
| Roles for workers + scale monitor | IAM | `03` |
| Redis token, SQL creds, push creds | Secrets Manager | `04` |
| Traffic rules between the new tiers | EC2 security groups | `02` |
| Logs, alarms, traces | CloudWatch | `09` |

> The **only** modification to existing infrastructure is one inline IAM policy on the EC2 instance
> role (`03-iam.md`). Get client sign-off on that specifically.

---

## Discovery commands

Run these in order and paste the answers into the variable block at the bottom.

**Account + region sanity**

```bash
aws sts get-caller-identity --query 'Account' --output text
aws configure get region
```

**VPC**

```bash
aws ec2 describe-vpcs \
  --query 'Vpcs[].{Id:VpcId,Cidr:CidrBlock,Default:IsDefault,Name:Tags[?Key==`Name`].Value|[0]}' \
  --output table
```

**The EC2 .NET host** — gives you the subnet, SG, and instance role to extend later

```bash
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Name:Tags[?Key==`Name`].Value|[0],Vpc:VpcId,Subnet:SubnetId,SGs:SecurityGroups[].GroupId,Profile:IamInstanceProfile.Arn}' \
  --output json
```

Resolve the instance profile to its **role name** (needed in `03`):

```bash
aws iam get-instance-profile --instance-profile-name <profile-name-from-above> \
  --query 'InstanceProfile.Roles[0].RoleName' --output text
```

**SQL Server (RDS)**

```bash
aws rds describe-db-instances \
  --query 'DBInstances[?contains(Engine,`sqlserver`)].{Id:DBInstanceIdentifier,Engine:Engine,Endpoint:Endpoint.Address,Port:Endpoint.Port,SGs:VpcSecurityGroups[].VpcSecurityGroupId,Subnets:DBSubnetGroup.Subnets[].SubnetIdentifier}' \
  --output json
```

**Subnets** — pick two private ones in different AZs for Redis + Fargate

```bash
aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,Cidr:CidrBlock,AutoPublicIp:MapPublicIpOnLaunch,Name:Tags[?Key==`Name`].Value|[0]}' \
  --output table
```

`AutoPublicIp: False` ⇒ private. Confirm each has a NAT route (next command).

**NAT gateway** — decides whether you need VPC endpoints in `02`, and gives the fixed egress IP Azure
will allow-list in `10`

```bash
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].{Id:NatGatewayId,Subnet:SubnetId,Ip:NatGatewayAddresses[].PublicIp}' \
  --output json
```

**Public entry point** — confirm only; we create nothing

```bash
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[].{Name:LoadBalancerName,Scheme:Scheme,DNS:DNSName}' --output table
aws apigateway get-rest-apis --query 'items[].{Id:id,Name:name}' --output table
```

**What is already there** (so you don't duplicate an existing cache/cluster)

```bash
aws elasticache describe-replication-groups --query 'ReplicationGroups[].ReplicationGroupId' --output text
aws ecs list-clusters --query 'clusterArns' --output text
aws sns list-platform-applications --query 'PlatformApplications[].PlatformApplicationArn' --output text
```

---

## Record the variables

Save as `vars.sh` (macOS) or `vars.ps1` (Windows) **outside git** — it holds infra IDs, not secrets,
but keep it out of the repo anyway. Every later file assumes these are set.

**macOS / Linux — `vars.sh`, then `source vars.sh`**

```bash
export AWS_PROFILE=cp-prod
export AWS_REGION=us-east-1
export ENV=prod                       # dev | staging | prod
export ACCOUNT_ID=<123456789012>

# --- existing (discovered) ---
export VPC_ID=<vpc-xxxx>
export SUBNET_A=<subnet-xxxx>         # private, AZ-a
export SUBNET_B=<subnet-yyyy>         # private, AZ-b
export EC2_INSTANCE_ID=<i-xxxx>
export EC2_SG_ID=<sg-xxxx>            # SG on the .NET host
export EC2_ROLE_NAME=<existing-ec2-role>
export SQL_HOST=<xxx.rds.amazonaws.com>
export SQL_SG_ID=<sg-yyyy>
export NAT_IP=<a.b.c.d>               # empty if no NAT — see 02

# --- new (filled in as you go) ---
export REDIS_SG_ID=
export WORKER_SG_ID=
export REDIS_ENDPOINT=
export ECR_URI=
export SNS_APP_IOS_ARN=
export SNS_APP_ANDROID_ARN=
```

**Windows — `vars.ps1`, then `. .\vars.ps1`**

```powershell
$env:AWS_PROFILE = "cp-prod"
$env:AWS_REGION  = "us-east-1"
$env:ENV         = "prod"
$env:ACCOUNT_ID  = "123456789012"
$env:VPC_ID      = "vpc-xxxx"
$env:SUBNET_A    = "subnet-xxxx"
$env:SUBNET_B    = "subnet-yyyy"
# ... same keys as above
```

---

## Naming + tagging convention

Apply to **every** new resource. Non-negotiable — teardown and cost attribution depend on it.

**Name:** `cp-<env>-<component>` — e.g. `cp-prod-dispatch-redis`, `cp-prod-dispatch-workers`,
`cp-prod-fieldjetx-ios`.

**Tags:** on every create call.

```
Key=Project,Value=stream1
Key=UseCase,Value=A
Key=Env,Value=$ENV
Key=ManagedBy,Value=techjays
Key=Runbook,Value=infra-setup
```

Find everything this runbook created, at any time:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=stream1 Key=Env,Values=$ENV \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
```

**Next:** [`02-networking.md`](02-networking.md)
