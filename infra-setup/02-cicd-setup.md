# 02 · CD — Build → ECR → ECS Deploy

**Prereq:** [`01-ecs-redis-setup.md`](01-ecs-redis-setup.md) through §7 done — the ECR repo, the ECS
cluster + service, `taskdef.json`, and the two task roles (`cp-$ENV-task-exec`, `cp-$ENV-task`) all
exist. This doc adds nothing to the running system except the pipeline that pushes new images and
redeploys the service, plus one new IAM user for that pipeline to authenticate as.

**Pick one CI provider.** This doc is written twice, back to back — **GitHub Actions** first, then
**Azure DevOps Pipelines**. Do the block for whichever one is actually wired to this repo; skip the
other.

**Auth model: one IAM user, one long-lived access key,** stored as an encrypted secret in whichever CI
system you use — not OIDC. An access key isn't scoped to a repo/branch/service-connection the way an
OIDC trust policy is, so the same user and key work for either provider; you only need one, regardless
of which CI you pick. The tradeoff versus OIDC: the key doesn't expire on its own and works from
anywhere, not just from this one pipeline — see the rotation note at the end of §1.

```
git push ──► CI pipeline (authenticates with IAM access key) ──► ECR ──► ECS service ──► task
```

| Built here | Name |
|---|---|
| IAM user | `cp-$ENV-cicd-deploy` |
| Access key | one, generated once in §1, pasted into the CI system's secret store in §2 |
| Pipeline definition | GitHub: `.github/workflows/deploy.yml` · Azure DevOps: `azure-pipelines.yml` + a service connection |

---

## 1. One-time: create the deploy IAM user

`cicd-deploy-policy.json` — hand-edit `REGION`/`ACCOUNT`/`ENV` (same treatment as `taskdef.json` in
`01-ecs-redis-setup.md` §7):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    { "Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart"], "Resource": "arn:aws:ecr:REGION:ACCOUNT:repository/cp/dispatch-worker" },
    { "Effect": "Allow", "Action": ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["ecs:UpdateService", "ecs:DescribeServices"], "Resource": "arn:aws:ecs:REGION:ACCOUNT:service/cp-ENV-dispatch/cp-ENV-dispatch-workers" },
    { "Effect": "Allow", "Action": "iam:PassRole", "Resource": ["arn:aws:iam::ACCOUNT:role/cp-ENV-task-exec", "arn:aws:iam::ACCOUNT:role/cp-ENV-task"] }
  ]
}
```

`iam:PassRole` is the one people forget — without it `RegisterTaskDefinition` fails with an opaque
`AccessDenied` on roles the pipeline never names directly.

**macOS / Linux**

```bash
aws iam create-user --user-name cp-$ENV-cicd-deploy \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV Key=ManagedBy,Value=techjays

aws iam put-user-policy --user-name cp-$ENV-cicd-deploy --policy-name deploy \
  --policy-document file://cicd-deploy-policy.json

aws iam create-access-key --user-name cp-$ENV-cicd-deploy
```

**Windows (PowerShell)**

```powershell
aws iam create-user --user-name "cp-$env:ENV-cicd-deploy" `
  --tags "Key=Project,Value=stream1" "Key=Env,Value=$env:ENV" "Key=ManagedBy,Value=techjays"

aws iam put-user-policy --user-name "cp-$env:ENV-cicd-deploy" --policy-name deploy `
  --policy-document file://cicd-deploy-policy.json

aws iam create-access-key --user-name "cp-$env:ENV-cicd-deploy"
```

`create-access-key` prints `AccessKeyId` and `SecretAccessKey` **once** — AWS does not store the secret
half and cannot show it again. Copy both straight into the CI secret store in §2 below; don't write them
to a vars file or anywhere else on disk (unlike the other vars this doc set uses, these two values should
exist in exactly one place: the CI system's encrypted secret store). If you lose the secret half,
`aws iam delete-access-key --user-name cp-$ENV-cicd-deploy --access-key-id <old-id>` and run
`create-access-key` again.

**Long-lived credentials.** This key doesn't expire on its own, and it works from anywhere it's typed
in, not just from this one pipeline. Rotate it on a schedule — `create-access-key` (a user can hold two
keys at once), swap the value in the CI secret store, verify a deploy, then `delete-access-key` the old
one — and treat any suspected exposure (committed to git, pasted somewhere public) as an immediate
rotation, not a wait-and-see.

---

## 2. Store the key in your CI system

### Option A — GitHub Actions

Repo → **Settings → Secrets and variables → Actions → New repository secret**, add both:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

If dev/staging/prod need different keys, use **Environments** (Settings → Environments) instead of
repo-level secrets — same two names, scoped per environment, and the workflow's `environment:` key picks
which set applies.

### Option B — Azure DevOps Pipelines

Project settings → **Service connections → New service connection → AWS** → authentication method
**Access Key ID / Secret Access Key** (not Workload identity federation) → paste both values from §1 →
name the connection (e.g. `cp-prod-cicd-deploy`) → grant the pipeline permission to use it on first run
(or pre-authorize under the connection's **Pipeline permissions**).

ADO encrypts the secret at rest and, like the AWS console, never displays it again after saving — the
one-shot rule from §1 applies on both ends.

---

## 3. The pipeline

### Option A — GitHub Actions

`.github/workflows/deploy.yml` in the worker repo, alongside the `taskdef.json` from
`01-ecs-redis-setup.md` §7. Runs on GitHub's own `ubuntu-latest` runner, not on your laptop, so it is
identical regardless of which OS you develop on:

```yaml
name: deploy
on:
  push:
    branches: [main]

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
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
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

Only the `configure-aws-credentials` step changed from the OIDC version — `aws-access-key-id` /
`aws-secret-access-key` instead of `role-to-assume`, and the workflow no longer needs
`permissions: id-token: write` since it isn't requesting an OIDC token at all.

### Option B — Azure DevOps Pipelines

`azure-pipelines.yml` at the repo root, alongside `taskdef.json`. The **AWS Toolkit for Azure DevOps**
extension ships an `ECRPushImage` task (the ADO equivalent of `amazon-ecr-login` + `docker push`), but
**no ECS-specific task** — there is no ADO equivalent of `amazon-ecs-render-task-definition` /
`amazon-ecs-deploy-task-definition`, so that half runs as plain `aws` CLI inside `AWSShellScript`, which
picks up the same access-key credentials from the service connection:

```yaml
trigger:
  branches:
    include: [main]

pool:
  vmImage: ubuntu-latest

variables:
  AWS_REGION: us-east-1
  ECR_REPO: cp/dispatch-worker
  CLUSTER: cp-prod-dispatch
  SERVICE: cp-prod-dispatch-workers
  AWS_CONN: cp-prod-cicd-deploy   # service connection name from §2

steps:
  - checkout: self

  - script: |
      set -euo pipefail
      docker build --platform linux/amd64 -t $(ECR_REPO):prod-$(Build.SourceVersion) .
    displayName: Build image

  - task: ECRPushImage@1
    displayName: Push image to ECR
    inputs:
      awsCredentials: $(AWS_CONN)
      regionName: $(AWS_REGION)
      imageSource: 'imagename'
      sourceImageName: $(ECR_REPO)
      sourceImageTag: prod-$(Build.SourceVersion)
      repositoryName: $(ECR_REPO)
      pushTag: prod-$(Build.SourceVersion)
      outputVariable: IMAGE_URI

  - task: AWSShellScript@1
    displayName: Render task definition and deploy
    inputs:
      awsCredentials: $(AWS_CONN)
      regionName: $(AWS_REGION)
      scriptType: inline
      inlineScript: |
        set -euo pipefail
        sed "s|ACCOUNT.dkr.ecr.REGION.amazonaws.com/cp/dispatch-worker:ENV-0.1.0|$(IMAGE_URI)|" \
          taskdef.json > taskdef.rendered.json

        aws ecs register-task-definition --cli-input-json file://taskdef.rendered.json

        aws ecs update-service --cluster $(CLUSTER) --service $(SERVICE) \
          --task-definition cp-prod-dispatch-worker --force-new-deployment

        aws ecs wait services-stable --cluster $(CLUSTER) --services $(SERVICE)
```

The task YAML is identical to the OIDC version — both `ECRPushImage@1` and `AWSShellScript@1` just take
`awsCredentials: <service connection name>` and don't care whether that connection holds an access key
or a federated identity. Only §1/§2 (how the connection itself authenticates) changed.

Keep the placeholder image line in `taskdef.json` exactly as committed in `01-ecs-redis-setup.md` §7
(`ACCOUNT.dkr.ecr.REGION.amazonaws.com/cp/dispatch-worker:ENV-0.1.0`) — the `sed` line above only works
while that literal string still matches. `--force-new-deployment` is required here because nothing else
in this script forces the service to pick up the newly registered revision.

---

## Notes — apply to either provider

- **The commit/build SHA is the image tag** (`github.sha` / `Build.SourceVersion`) — immutable, and
  rollback is redeploying an older SHA's task definition revision.
- **With `desired-count 0` the deploy still succeeds** — zero running tasks is a stable service. The new
  revision starts being used the next time `01-ecs-redis-setup.md` §8's toggle scales the service to 1.
- Both pipelines need the **ECR repo, log group, cluster, service, and task roles from
  `01-ecs-redis-setup.md` §5–§7 to already exist** — this doc only ever updates the service, it never
  creates one.
- **Rotate the access key on a schedule** (see §1) — this is the recurring cost of choosing access keys
  over OIDC; nothing else in this doc set does that bookkeeping for you.

---

## Teardown

Moved to its own file — see [`03-teardown.md`](03-teardown.md) §1.
