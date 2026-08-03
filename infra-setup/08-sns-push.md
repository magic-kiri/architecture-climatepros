# 08 · Amazon SNS — push to technician phones

**Status:** NEW · **Cloud:** AWS · **Used by:** UC-A only

Carries the accept/decline offer to the ranked technician's phone. §3: *APNs (iOS) + FCM (Android) · one
`Publish` call per device endpoint.* The worker calls `Publish` with `aioboto3`; SNS handles the APNs/FCM
protocols.

**Direct-to-device, no topics.** Each technician's device is its own SNS *platform endpoint*, so an offer
goes to exactly one phone. A topic would fan out to everyone — wrong for a cascading offer.

---

## Prereqs

`03` (task role with `sns:Publish`), `04` (`cp/$ENV/push/apns`, `cp/$ENV/push/fcm`).

From ClimatePros, per environment:

| Platform | What you need |
|---|---|
| iOS | APNs **token** auth: signing key `.p8`, key ID, team ID, bundle id — or a `.p12` cert |
| Android | Firebase **service-account JSON** (FCM HTTP v1) |

Dev builds use the APNs **sandbox** (`APNS_SANDBOX`); Prod uses `APNS`. Two different platform
applications — a sandbox token silently fails against the prod endpoint.

---

## Steps

### 1. iOS platform application

Token auth (`.p8`) — `apns-attrs.json`:

```json
{
  "PlatformCredential": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
  "PlatformPrincipal": "<APNS_KEY_ID>",
  "ApplePlatformTeamID": "<TEAM_ID>",
  "ApplePlatformBundleID": "com.climatepros.fieldjetx",
  "AuthenticationMethod": "TOKEN"
}
```

```bash
export SNS_APP_IOS_ARN=$(aws sns create-platform-application \
  --name cp-$ENV-fieldjetx-ios \
  --platform APNS \
  --attributes file://apns-attrs.json \
  --query 'PlatformApplicationArn' --output text)
echo $SNS_APP_IOS_ARN
```

For Dev/Staging use `--platform APNS_SANDBOX` and name it `cp-dev-fieldjetx-ios`.

### 2. Android platform application (FCM v1)

`fcm-attrs.json` — `PlatformCredential` is the whole service-account JSON, as a string:

```json
{
  "PlatformCredential": "{\"type\":\"service_account\",\"project_id\":\"...\",\"private_key\":\"-----BEGIN PRIVATE KEY-----\\n...\"}",
  "AuthenticationMethod": "TOKEN"
}
```

```bash
export SNS_APP_ANDROID_ARN=$(aws sns create-platform-application \
  --name cp-$ENV-fieldjetx-android \
  --platform GCM \
  --attributes file://fcm-attrs.json \
  --query 'PlatformApplicationArn' --output text)
```

`--platform GCM` is the correct value for FCM — the name is historical. `AuthenticationMethod=TOKEN`
selects HTTP v1; without it SNS assumes the retired legacy server-key API.

Both ARNs go into `vars.sh` and into the worker's task-definition environment (`07`).

### 3. Delivery-status logging (recommended)

Without this, a push that APNs rejects fails silently. Create a role SNS can use to write logs
(`trust-sns.json` with principal `sns.amazonaws.com`, then attach
`arn:aws:iam::aws:policy/service-role/AmazonSNSRole`), then:

```bash
aws sns set-platform-application-attributes \
  --platform-application-arn $SNS_APP_IOS_ARN \
  --attributes SuccessFeedbackRoleArn=arn:aws:iam::$ACCOUNT_ID:role/cp-sns-delivery-logs,FailureFeedbackRoleArn=arn:aws:iam::$ACCOUNT_ID:role/cp-sns-delivery-logs,SuccessFeedbackSampleRate=10
```

Repeat for `$SNS_APP_ANDROID_ARN`. Failures are logged at 100% regardless of the sample rate.

### 4. Device endpoints — runtime, not setup

`POST /devices/register` on the .NET API creates one endpoint per device when a technician logs in:

```bash
# what the API does; useful once by hand to test
aws sns create-platform-endpoint \
  --platform-application-arn $SNS_APP_IOS_ARN \
  --token <device-token-from-the-app> \
  --custom-user-data "technician_id=12345"
```

Store the returned endpoint ARN against the technician in SQL Server — the worker publishes to that ARN.

---

## Verify

```bash
aws sns list-platform-applications \
  --query 'PlatformApplications[].{Arn:PlatformApplicationArn,Enabled:Attributes.Enabled}' --output table

# real push to a test device
aws sns publish --target-arn <endpoint-arn> \
  --message '{"APNS":"{\"aps\":{\"alert\":\"Dispatch offer - test\"}}"}' \
  --message-structure json
```

Returns a `MessageId` and the phone shows the notification. `EndpointDisabled` ⇒ a stale device token;
the app must re-register.

---

## Talks to

| From | To | Protocol | Auth |
|---|---|---|---|
| ECS dispatch worker | SNS `Publish` | 443 | task-role IAM |
| SNS | APNs / FCM → phone | AWS-managed | platform credential |
| Mobile app | `.NET POST /devices/register` → `create-platform-endpoint` | 443 | user session |

**The reply does not come back through SNS.** The technician taps Accept in the app, which `POST`s to
`/dispatches/{id}/respond` on the .NET API; the API `LPUSH`es onto the per-technician Redis reply list and
the worker's `BLPOP` wakes instantly. Push is one-way — see
[`11-service-communication.md`](11-service-communication.md).

---

## Cost

$0.50 per 1,000,000 mobile pushes, **first 1M/month free**. APNs and FCM themselves are free. §10's
volume — 500 dispatches/day × 5 technicians × 30 = 75,000/mo — is **$0**.

---

## Gotchas

- Sandbox vs production APNs is the single most common failure. `APNS_SANDBOX` for debug builds, `APNS`
  for App Store/TestFlight builds. Mixing them = pushes that vanish.
- Device tokens rotate (reinstall, OS update). The app must re-register on every launch, and disabled
  endpoints need cleaning up or `Publish` starts erroring.
- No topics for offers. The cascade in §5 is sequential — technician 1, timeout, technician 2 — which
  requires per-device publishes.
- Push is best-effort. A phone in a basement gets nothing; the offer TTL and cascade in the dispatch
  logic are what make that safe, not SNS retries.
- Rotating APNs keys = `set-platform-application-attributes`, no need to recreate endpoints.

**Next:** [`09-cloudwatch.md`](09-cloudwatch.md)
