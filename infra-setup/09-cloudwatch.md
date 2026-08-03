# 09 · CloudWatch — logs, alarms, traces

**Status:** NEW · **Cloud:** AWS · **Used by:** all AWS-side components

§3: *every service emits traces and logs via OpenTelemetry, viewed through CloudWatch on the AWS side and
Azure Monitor for the AI stack.* This file covers the AWS half. The AI stack's observability (`llm_calls`,
eval sets) lives on Azure and is out of scope.

Three questions this has to answer for Use Case A:

1. Is the queue backing up or evicting? (an evicted entry is a lost job)
2. Are the workers actually running when a division is toggled on?
3. Are pushes reaching phones?

---

## Prereqs

`05` (Redis), `07` (cluster + service + log group), `08` (SNS apps).

---

## Steps

### 1. Log groups + retention

`/ecs/cp-$ENV-dispatch-worker` was created in `07`. Add the rest:

```bash
for LG in /ecs/cp-$ENV-dispatch-worker /aws/sns/cp-$ENV-delivery /cp/$ENV/dispatch/audit; do
  aws logs create-log-group --log-group-name $LG \
    --tags Project=stream1,UseCase=A,Env=$ENV,ManagedBy=techjays 2>/dev/null
  aws logs put-retention-policy --log-group-name $LG --retention-in-days 30
done
```

Retention is the whole cost story — a group with no retention policy keeps logs **forever** and bills
storage forever. 30 days for Dev/Staging, 90 for Prod audit.

### 2. Alarms that matter

An SNS topic for operator notification (separate from the push apps in `08`):

```bash
export ALARM_TOPIC=$(aws sns create-topic --name cp-$ENV-dispatch-alarms \
  --tags Key=Project,Value=stream1 Key=Env,Value=$ENV --query 'TopicArn' --output text)

aws sns subscribe --topic-arn $ALARM_TOPIC --protocol email --notification-endpoint ops@techjays.com
```

**a. Redis evictions — must stay at zero.** This is the "we lost a job" alarm.

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name cp-$ENV-dispatch-redis-evictions \
  --alarm-description "Dispatch queue evicted an entry - a job may have been dropped" \
  --namespace AWS/ElastiCache --metric-name Evictions --statistic Sum \
  --dimensions Name=ReplicationGroupId,Value=cp-$ENV-dispatch-redis \
  --period 300 --evaluation-periods 1 --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions $ALARM_TOPIC
```

**b. Redis memory pressure — the early warning for (a).**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name cp-$ENV-dispatch-redis-memory \
  --namespace AWS/ElastiCache --metric-name DatabaseMemoryUsagePercentage --statistic Average \
  --dimensions Name=ReplicationGroupId,Value=cp-$ENV-dispatch-redis \
  --period 300 --evaluation-periods 2 --threshold 75 \
  --comparison-operator GreaterThanThreshold --alarm-actions $ALARM_TOPIC
```

**c. Push failures.**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name cp-$ENV-dispatch-push-failures \
  --namespace AWS/SNS --metric-name NumberOfNotificationsFailed --statistic Sum \
  --period 300 --evaluation-periods 1 --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching --alarm-actions $ALARM_TOPIC
```

**d. Worker crash-loop.** Metric filter on the log group, then alarm on it:

```bash
aws logs put-metric-filter \
  --log-group-name /ecs/cp-$ENV-dispatch-worker \
  --filter-name worker-errors \
  --filter-pattern '?ERROR ?CRITICAL ?Traceback' \
  --metric-transformations metricName=DispatchWorkerErrors,metricNamespace=CP/Dispatch,metricValue=1,defaultValue=0

aws cloudwatch put-metric-alarm \
  --alarm-name cp-$ENV-dispatch-worker-errors \
  --namespace CP/Dispatch --metric-name DispatchWorkerErrors --statistic Sum \
  --period 300 --evaluation-periods 1 --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching --alarm-actions $ALARM_TOPIC
```

> **Deliberately no alarm on `RunningTaskCount == 0`.** Zero is the correct, cheap state when every
> division has the toggle off. Alarming on it would page ops for working as designed. What you want
> instead is a **queue-depth** alarm — entries waiting with no consumer — which needs the worker to
> publish `XLEN`/pending-entries as a custom metric (`cloudwatch:PutMetricData` is already in the task
> role from `03`). Add that alarm once the worker emits the metric.

### 3. OpenTelemetry traces

Add the AWS Distro for OpenTelemetry collector as a **sidecar** in the `07` task definition — the worker
already points `OTEL_EXPORTER_OTLP_ENDPOINT` at `localhost:4317`:

```json
{
  "name": "aws-otel-collector",
  "image": "public.ecr.aws/aws-observability/aws-otel-collector:latest",
  "essential": false,
  "command": ["--config=/etc/ecs/ecs-default-config.yaml"],
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/cp-ENV-dispatch-worker",
      "awslogs-region": "REGION",
      "awslogs-stream-prefix": "otel"
    }
  }
}
```

`essential: false` — a collector failure must never kill a dispatch. Traces land in X-Ray and metrics in
CloudWatch; the task role already carries `xray:PutTraceSegments`.

The trace should span the whole loop: `.NET XADD → worker XREADGROUP → SNS Publish → technician reply →
SQL write → XACK`. Propagate the dispatch id as the trace id so one dispatch is one trace.

### 4. Dashboard

```bash
aws cloudwatch put-dashboard --dashboard-name cp-$ENV-dispatch \
  --dashboard-body file://dashboard.json
```

Six widgets are enough: Redis `CurrConnections` · `DatabaseMemoryUsagePercentage` · `Evictions` ·
ECS `RunningTaskCount` + `CPUUtilization` · SNS `NumberOfNotificationsFailed` · the worker error-log
metric filter.

---

## Verify

```bash
aws cloudwatch describe-alarms --alarm-name-prefix cp-$ENV-dispatch \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' --output table

aws logs describe-log-groups --log-group-name-prefix /ecs/cp-$ENV \
  --query 'logGroups[].{Name:logGroupName,Retention:retentionInDays}' --output table

aws logs tail /ecs/cp-$ENV-dispatch-worker --since 15m
```

All alarms should read `OK` or `INSUFFICIENT_DATA` — `INSUFFICIENT_DATA` is normal before the first
dispatch. Confirm the email subscription was accepted, or the alarms notify nobody.

---

## Talks to

| From | To | Protocol |
|---|---|---|
| ECS worker (awslogs driver + OTel sidecar) | CloudWatch Logs / X-Ray | 443 |
| ElastiCache, ECS, SNS | CloudWatch metrics | AWS-internal, automatic |
| CloudWatch alarms | `cp-$ENV-dispatch-alarms` SNS topic → email | AWS-internal |

The Azure AI stack reports to **Azure Monitor**, not here. A single trace spanning both clouds requires
OTel context propagation across the seam in `10` — design item, not an infra command.

---

## Cost

Ingestion $0.50/GB, storage $0.03/GB-month, first 10 alarms free then $0.10 each, custom metrics
$0.30/metric-month. A scale-to-zero worker generates little — **low single-digit dollars/month**. §10
budgets $15–30/mo for observability across the whole system, most of it on the Azure side.

---

## Gotchas

- No retention policy = infinite retention = the bill that creeps. Set it on **every** group at creation.
- `--treat-missing-data notBreaching` matters here: with the workers at zero, most metrics report no data
  and the default (`missing = breaching`) would page ops constantly.
- Container Insights must be on at the cluster (`07` step 2) or ECS task-level metrics are absent.
- The `Evictions > 0` alarm is the one to wire to a human. Everything else can wait for business hours.

**Next:** [`10-cross-cloud-seam.md`](10-cross-cloud-seam.md)
