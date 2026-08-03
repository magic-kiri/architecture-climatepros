# 06 · Amazon ECR — dispatch-worker image registry

**Status:** NEW · **Cloud:** AWS · **Used by:** UC-A

ECS Fargate can only run an image it can pull. ECR is the private registry for the Python 3.11 async
dispatch worker (§3: `asyncio`, `redis.asyncio`, `aioboto3`, `httpx`).

Not in the HLD component list because it is plumbing, not a runtime tier — but Fargate cannot start
without it.

---

## Prereqs

Docker Desktop running. The worker source with a `Dockerfile`.

> **This is the one file that needs a Docker daemon.** If you are working from **AWS CloudShell**
> (`00` §2d), there is no Docker there — steps 3 and 4 will fail. Three ways round it:
>
> | Option | When |
> |---|---|
> | **AWS CodeBuild** — `aws codebuild start-build`, builds and pushes server-side | no local Docker, no CI yet |
> | **CI pipeline** — GitHub Actions with an OIDC role, `docker build` + `push` in the job | the right long-term answer |
> | **The existing EC2 host** — install Docker, build there | quickest one-off, but it puts a build toolchain on a production host |
>
> Steps 1 and 2 (create the repository, lifecycle policy) work fine in CloudShell.

---

## Steps

### 1. Create the repository

```bash
aws ecr create-repository \
  --repository-name cp/dispatch-worker \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE \
  --encryption-configuration encryptionType=AES256 \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=ManagedBy,Value=techjays
```

One repository serves all three environments — separate them by tag (`prod-0.1.0`, `dev-0.1.0`), not
by repository. `IMMUTABLE` means a tag can never be silently overwritten, so a rollback to
`prod-0.1.0` gets the same bytes it got last week.

```bash
export ECR_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cp/dispatch-worker
echo $ECR_URI
```

### 2. Lifecycle policy — stop paying for old images

`lifecycle.json`:

```json
{
  "rules": [{
    "rulePriority": 1,
    "description": "Keep the 10 most recent images",
    "selection": { "tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 10 },
    "action": { "type": "expire" }
  }]
}
```

```bash
aws ecr put-lifecycle-policy --repository-name cp/dispatch-worker \
  --lifecycle-policy-text file://lifecycle.json
```

### 3. Authenticate Docker to ECR

Token lasts 12 hours; re-run when a push starts failing with `no basic auth credentials`.

**macOS / Linux**

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

**Windows PowerShell**

```powershell
aws ecr get-login-password --region $env:AWS_REGION | `
  docker login --username AWS --password-stdin "$($env:ACCOUNT_ID).dkr.ecr.$($env:AWS_REGION).amazonaws.com"
```

### 4. Build and push

```bash
docker build --platform linux/amd64 -t cp/dispatch-worker:$ENV-0.1.0 .
docker tag  cp/dispatch-worker:$ENV-0.1.0 $ECR_URI:$ENV-0.1.0
docker push $ECR_URI:$ENV-0.1.0
```

> **`--platform linux/amd64` is mandatory on Apple Silicon.** Without it you push an `arm64` image and
> the Fargate task dies with `exec format error`. (You *can* run ARM on Fargate by setting
> `runtimePlatform.cpuArchitecture: ARM64` in the task definition — pick one and stay consistent.
> This runbook uses X86_64.)

---

## Verify

```bash
aws ecr describe-images --repository-name cp/dispatch-worker \
  --query 'sort_by(imageDetails,&imagePushedAt)[-3:].{Tags:imageTags,Pushed:imagePushedAt,MB:imageSizeInBytes}' \
  --output table

# vulnerability scan result
aws ecr describe-image-scan-findings --repository-name cp/dispatch-worker \
  --image-id imageTag=$ENV-0.1.0 \
  --query 'imageScanFindings.findingSeverityCounts' --output json
```

Record the full image URI — `07`'s task definition needs it verbatim:

```
<account>.dkr.ecr.<region>.amazonaws.com/cp/dispatch-worker:prod-0.1.0
```

---

## Talks to

| From | To | Why |
|---|---|---|
| developer laptop / CI | ECR (443) | `docker push` |
| ECS task-exec role | ECR (443, via NAT or `ecr.api`+`ecr.dkr` endpoints) | image pull at task start |

Nothing else. ECR never initiates a connection.

---

## Cost

$0.10 per GB-month stored. A slim Python worker image is ~200 MB; ten of them ≈ **$0.20/mo**. Data
transfer inside the region is free — which is why the pull path matters (`02` step 5).

---

## Gotchas

- Always pin a **tag or digest** in the task definition. `:latest` plus `IMMUTABLE` is a contradiction,
  and `:latest` makes rollback guesswork.
- Push from CI, not laptops, once the pipeline exists. The commands above are for the first bring-up.
- Login expires every 12 h. It is not a permissions problem.
- Tag with the environment (`prod-0.1.0`) so a Dev image can never be promoted by accident.

**Next:** [`07-ecs-fargate.md`](07-ecs-fargate.md)
