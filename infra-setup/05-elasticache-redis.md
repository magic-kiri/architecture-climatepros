# 05 · Amazon ElastiCache for Redis — the dispatch queue

**Status:** NEW · **Cloud:** AWS · **Used by:** UC-A only

The durable dispatch queue. §3/§4 name this as the **decided** implementation of the "message broker"
the HLD diagram still shows as TBD — Redis Streams with consumer groups and replay, plus two things
only Redis gives you cheaply:

| Use | Redis feature |
|---|---|
| Queue of dispatches, replayable, at-least-once | Streams — `XADD` / `XREADGROUP` / `XACK` / `XCLAIM` |
| One worker per division at a time | `SETNX` lock with TTL |
| Worker wakes the instant a technician replies — no polling | per-technician reply list, `LPUSH` / `BLPOP` |
| Reply de-duplication | `SETNX resp:done` |

**The queue must never evict.** A dropped stream entry is a job that silently never gets dispatched.

---

## Prereqs

`02` complete (`REDIS_SG_ID`), `04` complete (`REDIS_AUTH_TOKEN` in the shell and in Secrets Manager).

---

## Steps

### 1. Cache subnet group — the two private subnets from `01`

```bash
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name cp-$ENV-dispatch-redis-subnets \
  --cache-subnet-group-description "Stream 1 dispatch queue subnets" \
  --subnet-ids $SUBNET_A $SUBNET_B
```

### 2. Parameter group — turn eviction off

```bash
aws elasticache create-cache-parameter-group \
  --cache-parameter-group-name cp-$ENV-dispatch-redis7 \
  --cache-parameter-group-family redis7 \
  --description "No eviction - dispatch queue must not lose entries"

aws elasticache modify-cache-parameter-group \
  --cache-parameter-group-name cp-$ENV-dispatch-redis7 \
  --parameter-name-values "ParameterName=maxmemory-policy,ParameterValue=noeviction"
```

With `noeviction`, a full cache makes writes **fail loudly** instead of silently dropping the oldest
entries. The `XADD` error is what you want — the CloudWatch alarm in `09` fires on it.

### 3. Create the replication group

Cluster mode stays **disabled** — Streams, `BLPOP` and multi-key division locks all assume one keyspace.

**Prod (Multi-AZ, 1 primary + 1 replica):**

```bash
aws elasticache create-replication-group \
  --replication-group-id cp-$ENV-dispatch-redis \
  --replication-group-description "Stream 1 Auto-Dispatch queue (Redis Streams)" \
  --engine redis --engine-version 7.1 \
  --cache-node-type cache.t4g.small \
  --num-cache-clusters 2 \
  --automatic-failover-enabled --multi-az-enabled \
  --cache-subnet-group-name cp-$ENV-dispatch-redis-subnets \
  --cache-parameter-group-name cp-$ENV-dispatch-redis7 \
  --security-group-ids $REDIS_SG_ID \
  --transit-encryption-enabled --transit-encryption-mode required \
  --at-rest-encryption-enabled \
  --auth-token "$REDIS_AUTH_TOKEN" \
  --snapshot-retention-limit 7 --snapshot-window 05:00-06:00 \
  --preferred-maintenance-window sun:07:00-sun:08:00 \
  --tags Key=Project,Value=stream1 Key=UseCase,Value=A Key=Env,Value=$ENV Key=ManagedBy,Value=techjays
```

**Dev / Staging** — same command with `--num-cache-clusters 1`, and drop
`--automatic-failover-enabled --multi-az-enabled`. Halves the bill.

### 4. Wait, then capture the endpoint

Takes 5–10 minutes.

```bash
aws elasticache wait replication-group-available --replication-group-id cp-$ENV-dispatch-redis

export REDIS_ENDPOINT=$(aws elasticache describe-replication-groups \
  --replication-group-id cp-$ENV-dispatch-redis \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' --output text)
echo $REDIS_ENDPOINT
```

Add `REDIS_ENDPOINT` to `vars.sh`. It goes into the worker task definition (`07`) and the .NET host's
config.

---

## Verify

```bash
# state, encryption, eviction policy
aws elasticache describe-replication-groups --replication-group-id cp-$ENV-dispatch-redis \
  --query 'ReplicationGroups[0].{Status:Status,TLS:TransitEncryptionEnabled,Auth:AuthTokenEnabled,MultiAZ:MultiAZ,Nodes:length(MemberClusters)}' \
  --output table

aws elasticache describe-cache-parameters --cache-parameter-group-name cp-$ENV-dispatch-redis7 \
  --query 'Parameters[?ParameterName==`maxmemory-policy`].ParameterValue' --output text
# must print: noeviction
```

**Connectivity test — from inside the VPC only.** There is no public endpoint. SSM into the EC2 host
and use `redis-cli` with TLS + AUTH:

```bash
redis-cli -h $REDIS_ENDPOINT -p 6379 --tls -a "$REDIS_AUTH_TOKEN" PING
# PONG

# smoke-test the actual pattern the design uses
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XADD dispatch:stream '*' job_id test-1
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XGROUP CREATE dispatch:stream workers 0
redis-cli -h $REDIS_ENDPOINT --tls -a "$REDIS_AUTH_TOKEN" XREADGROUP GROUP workers w1 COUNT 1 STREAMS dispatch:stream '>'
```

Timeout instead of `PONG` ⇒ the SG rule in `02` step 3 is missing.

> The consumer group is created by the worker at start-up in the real system; the command above is only
> to prove the endpoint works. Delete the test key afterwards: `DEL dispatch:stream`.

---

## Talks to

| Direction | Peer | Protocol | Auth |
|---|---|---|---|
| in | .NET Microservices API on EC2 | 6379 TLS | AUTH token |
| in | ECS Fargate dispatch workers | 6379 TLS | AUTH token |
| out | — | — | Redis initiates nothing |

Never reached from the internet, from the mobile app, or from the Azure AI server.

---

## Cost

`cache.t4g.small` ≈ **$0.032/hr ⇒ ~$23.36/mo** per node, always on (§10). Prod Multi-AZ = 2 nodes
⇒ ~$47/mo. This is the **fixed floor** of the new AWS tier — it does not scale to zero with the
workers, because the queue must survive between dispatches.

---

## Gotchas

- `--auth-token` requires `--transit-encryption-enabled`. Tokens cannot contain `/ " @` or spaces.
- The AUTH token **cannot be set after creation** without a rotation call — get it right the first time.
- The client must speak TLS. `redis.asyncio` needs `ssl=True`; a plaintext client just times out.
- Sizing follows queue depth, not throughput. `cache.t4g.small` (1.37 GB) holds far more dispatch
  entries than 46 branches generate — trim the stream (`XTRIM MAXLEN`) as a habit, not as capacity
  management.
- One replication group per environment. Sharing one across Dev and Prod puts test dispatches in the
  live consumer group.

**Next:** [`06-ecr.md`](06-ecr.md)
