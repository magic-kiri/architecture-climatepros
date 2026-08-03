# 00 · AWS CLI — first-time setup (macOS + Windows)

**Status:** prerequisite · **Creates nothing.** Get a working `aws` command authenticated against the
ClimatePros account before touching any other file.

---

## 1. Install

### macOS

```bash
brew install awscli
```

### Windows (PowerShell)

```powershell
winget install --id Amazon.AWSCLI --source winget
```

Close and reopen the terminal (PATH refresh), then confirm — must print `aws-cli/2.x`:

```bash
aws --version
```

Also install **Docker Desktop** (needed only for `06-ecr.md` / `07-ecs-fargate.md`) and **git**.

---

## 2. Get an access key

The console password does not work for the CLI — it needs an **Access Key ID** + **Secret Access Key**.

1. Open <https://console.aws.amazon.com/iam/home#/security_credentials>
   (or top-right account menu → **Security credentials**).
2. **Access keys** → **Create access key**.
3. Use case → **Command Line Interface (CLI)** → tick the acknowledgement → **Next**.
4. Description tag: `cli-<your-name>-<laptop>` → **Create access key**.
5. **Download .csv file** — the secret is shown only on this screen.

Also note the **Account ID** (account menu) and **Region** (top-right selector) — `01` needs both. The
region must be the one the existing FieldJetX EC2 host and SQL Server run in.

> **Never create access keys on the root user** (the account you log in to with an email address). A root
> key cannot be scoped by any policy and compromises the entire account if it leaks. Create an IAM user
> first, then make the key as that user.

---

## 3. Configure the profile

Open the downloaded `.csv` and paste its two values here. Identical on macOS and Windows:

```bash
aws configure --profile cp-prod
# AWS Access Key ID     : AKIA...            <- "Access key ID" column
# AWS Secret Access Key : ****               <- "Secret access key" column
# Default region name   : us-east-1          <- the region from §2
# Default output format : json
```

`cp-prod` is a local label in `~/.aws/config` — nothing on the AWS side knows it. Later files use this
name, so keep it. Don't use `default`; a named profile is what stops a stray command hitting the wrong
account.

Never commit the files this writes.

---

## 4. Make the profile stick

Every command in this runbook assumes the profile is already in the environment. Set it once — `export`
alone only lasts until you close the terminal.

**macOS / Linux** (`~/.zshrc` for zsh, the macOS default; `~/.bash_profile` for bash):

```bash
echo 'export AWS_PROFILE=cp-prod' >> ~/.zshrc
source ~/.zshrc
```

**Windows (PowerShell)** — user-level, applies to every new shell:

```powershell
[Environment]::SetEnvironmentVariable("AWS_PROFILE", "cp-prod", "User")
```

No `AWS_REGION` needed — §3 already stored the region in the profile.

---

## 5. Verify

```bash
# with explicit profile
aws sts get-caller-identity --profile cp-test

# or if AWS_PROFILE is already set in the environment
aws sts get-caller-identity
```

Expected — account id and the user ARN:

```json
{ "UserId": "...", "Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/..." }
```

If this fails, stop. Nothing else in the runbook will work.

This only proves the credentials are valid, not that you can create anything — `01`'s discovery commands
are the real test. Which services each person needs is listed in
[`../md-files/cloud-access-request.md`](../md-files/cloud-access-request.md).

---

## 6. If §5 works but everything else returns `AccessDenied`

MFA is enforced for API calls. Trade the key for a temporary session:

```bash
aws sts get-session-token \
  --serial-number arn:aws:iam::<account-id>:mfa/<your-user> \
  --token-code <6-digits>
```

Put the three returned values (`AccessKeyId`, `SecretAccessKey`, `SessionToken`) into the profile and
repeat every 12 hours.

---

## Cross-platform rules used by every later file

The commands are written **once** in bash form and work in PowerShell too, provided you follow these:

| Difference | macOS / Linux | Windows PowerShell |
|---|---|---|
| Set a variable | `export VPC_ID=vpc-123` | `$env:VPC_ID = "vpc-123"` |
| Read a variable | `$VPC_ID` | `$env:VPC_ID` |
| Line continuation | trailing `\` | trailing backtick `` ` `` |
| Inline JSON argument | works quoted | **breaks** — use `file://payload.json` |

Two habits keep the command text identical on both platforms — used throughout:

1. **Pass JSON from a file**, never inline: `--cli-input-json file://taskdef.json`.
2. **Read output with `--query` + `--output text`**, never `jq` (not installed on Windows):
   `aws elasticache describe-... --query 'X[0].Y' --output text`.

Windows tip: run everything from **PowerShell 7+**, not `cmd.exe`. `git bash` also works and lets you use
the bash column verbatim.

---

## Safety before you provision

- Confirm the region matches the existing platform — a new Redis in the wrong region cannot reach the
  existing VPC.
- Add `--dry-run` where supported (most `ec2` calls) on the first attempt.
- Every create command in this runbook carries `--tags`. Untagged resources cannot be cost-attributed or
  safely torn down later.

**Next:** [`01-existing-vs-new.md`](01-existing-vs-new.md)
