# 03 · Teardown

**Prereq:** whichever of [`01-ecs-redis-setup.md`](01-ecs-redis-setup.md) /
[`02-cicd-setup.md`](02-cicd-setup.md) you actually ran — only tear down what you built. Everything in
this doc set is new and deletable; nothing pre-existing is touched by any of it.

Reverse build order: `02` was created after `01`, so it's undone first. Skip §1 if you never ran `02`.

---

## 1. CD — deploy user (undoes `02-cicd-setup.md`)

Not part of the `01` loop below — that one only knows about roles, not IAM users. Deleting a user means
deleting its keys and inline policy first:

**macOS / Linux**

```bash
for K in $(aws iam list-access-keys --user-name cp-$ENV-cicd-deploy --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name cp-$ENV-cicd-deploy --access-key-id $K
done
aws iam delete-user-policy --user-name cp-$ENV-cicd-deploy --policy-name deploy
aws iam delete-user --user-name cp-$ENV-cicd-deploy
```

**Windows (PowerShell)**

```powershell
$keys = (aws iam list-access-keys --user-name "cp-$env:ENV-cicd-deploy" --query 'AccessKeyMetadata[].AccessKeyId' --output text) -split '\s+' | Where-Object { $_ }
foreach ($K in $keys) {
  aws iam delete-access-key --user-name "cp-$env:ENV-cicd-deploy" --access-key-id $K
}
aws iam delete-user-policy --user-name "cp-$env:ENV-cicd-deploy" --policy-name deploy
aws iam delete-user --user-name "cp-$env:ENV-cicd-deploy"
```

Then delete the matching GitHub repository secret / Azure DevOps service connection so nothing points at
a now-deleted key.

---

## 2. Core infra (undoes `01-ecs-redis-setup.md`)

Reverse order. Everything here is new, so nothing survives.

**macOS / Linux**

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

**Windows (PowerShell)**

```powershell
aws ecs update-service --cluster "cp-$env:ENV-dispatch" --service "cp-$env:ENV-dispatch-workers" --desired-count 0
aws ecs delete-service --cluster "cp-$env:ENV-dispatch" --service "cp-$env:ENV-dispatch-workers" --force
aws ecs delete-cluster --cluster "cp-$env:ENV-dispatch"
aws elasticache delete-replication-group --replication-group-id "cp-$env:ENV-dispatch-redis"
aws elasticache wait replication-group-deleted --replication-group-id "cp-$env:ENV-dispatch-redis"
aws elasticache delete-cache-subnet-group --cache-subnet-group-name "cp-$env:ENV-redis-subnets"
aws ecr delete-repository --repository-name cp/dispatch-worker --force
aws logs delete-log-group --log-group-name "/ecs/cp-$env:ENV-dispatch-worker"
aws secretsmanager delete-secret --secret-id "cp/$env:ENV/redis-auth-token" --force-delete-without-recovery

aws ec2 delete-security-group --group-id $env:REDIS_SG_ID
aws ec2 delete-security-group --group-id $env:WORKER_SG_ID
aws ec2 detach-internet-gateway --vpc-id $env:VPC_ID --internet-gateway-id $env:IGW_ID
aws ec2 delete-internet-gateway --internet-gateway-id $env:IGW_ID
aws ec2 delete-subnet --subnet-id $env:SUBNET_A
aws ec2 delete-subnet --subnet-id $env:SUBNET_B
aws ec2 delete-route-table --route-table-id $env:RTB_ID
aws ec2 delete-vpc --vpc-id $env:VPC_ID
```

Delete the roles too — they cost nothing but they accumulate. The CD principal from `02-cicd-setup.md`
is an IAM **user**, not a role — it's handled in §1 above, not this loop:

**macOS / Linux**

```bash
for R in cp-$ENV-task-exec cp-$ENV-task; do
  for P in $(aws iam list-role-policies --role-name $R --query 'PolicyNames' --output text); do
    aws iam delete-role-policy --role-name $R --policy-name $P
  done
  for A in $(aws iam list-attached-role-policies --role-name $R --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name $R --policy-arn $A
  done
  aws iam delete-role --role-name $R
done
```

**Windows (PowerShell)**

```powershell
$roles = @("cp-$env:ENV-task-exec", "cp-$env:ENV-task")
foreach ($R in $roles) {
  $policyNames = (aws iam list-role-policies --role-name $R --query 'PolicyNames' --output text) -split '\s+' | Where-Object { $_ }
  foreach ($P in $policyNames) {
    aws iam delete-role-policy --role-name $R --policy-name $P
  }
  $attached = (aws iam list-attached-role-policies --role-name $R --query 'AttachedPolicies[].PolicyArn' --output text) -split '\s+' | Where-Object { $_ }
  foreach ($A in $attached) {
    aws iam detach-role-policy --role-name $R --policy-arn $A
  }
  aws iam delete-role --role-name $R
}
```

---

## 3. Verify nothing is left

Find anything either doc created, at any time — identical either OS apart from the continuation
character:

**macOS / Linux**

```bash
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=stream1 \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
```

**Windows (PowerShell)**

```powershell
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=stream1 `
  --query 'ResourceTagMappingList[].ResourceARN' --output text
```

An empty result means it's all gone. The IAM user/role deletions above don't carry the `Project` tag
lookup reliably for all resource types — if this still lists something, `describe`/`get` it by ARN to
see what survived and delete it by hand.
