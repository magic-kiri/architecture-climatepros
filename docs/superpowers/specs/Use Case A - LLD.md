# Use Case A · Auto-Dispatch Worker — Low-Level Design

**Date:** 2026-07-31
**Scope:** the Auto-Dispatch worker tier only — §1 Overview, §2 Architecture, §4 Infrastructure, §6 Core Logic of `stream1-unified-architecture.html`, Use Case A.
**Out of scope:** Use Cases B and C. Ranking weights per branch (already specified in §6). Mobile app UI. API request/response schemas (endpoint names only, per instruction).

---

## 1. Why this document exists

`sections/05.html` and `sections/06.html` describe *what* Auto-Dispatch does — the assignment loop and the weighted-sum ranking. They do not describe *how the worker survives*: 100 concurrent dispatches, a technician who accepts two jobs at once, a dispatcher flipping a branch toggle mid-cascade, Redis dying, or a deploy landing mid-dispatch.

This document pins the worker's internal design so those cases are answered by construction rather than patched later.

Two changes to the previously documented architecture drive everything here:

1. **The worker never touches SQL Server.** All reads and writes go through the .NET Microservices API — starting with `GET /api/dispatch/GetNearestVehicles`, which returns the candidate technician list with each technician's prior-visit count, real road distance, and drive duration to the jobsite. This supersedes the "ECS workers read/write SQL Server directly" wiring in `sections/02.html` and `sections/04.html`.
2. **The worker is an event-driven state machine, not a task-per-dispatch runner.** Nothing sleeps or blocks for the 5–10 minutes a dispatch takes to resolve.

---

## 2. Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | Event-driven state machine. No long-lived coroutine per dispatch. | A dispatch takes 5–10 min. Deploys are more frequent than that, so any in-memory hold loses in-flight work on every release. Also the only shape where a branch toggle can halt a dispatch that is "waiting" — there is nothing to cancel. |
| D2 | All worker↔data access through the .NET API. | Single owner of SQL Server. Worker holds no DB credentials, no connection pool, no schema coupling. |
| D3 | Concurrency gate is a **global cap on outbound .NET calls**, not a per-branch in-flight cap. | The scarce resource is the legacy .NET/SQL tier. In-flight dispatches are just rows and cost nothing. |
| D4 | **Redis is a nudge; SQL is truth.** Every event is written to a SQL inbox table by .NET, then Redis is pinged best-effort. | Makes Redis a pure latency optimisation. It cannot cause data loss, so "Redis is down" degrades from ~50ms to ~1.5s instead of failing. |
| D5 | .NET fans out to the dispatch board (SignalR) as a side effect of the state-persist call it already receives. | Worker is on a private subnet with no stable address; a browser can never reach it. .NET already sits between both sides. Zero new components, zero extra calls. |
| D6 | Ranking: `eta_i = free_i + driveMin_i`. `free_i` is the technician-submitted "I'm free in N min" **for his current job only**. `driveMin_i` is real drive duration from Azuga/Google, supplied by `GetNearestVehicles`. | Removes the `dist / AVG_SPEED` approximation currently in §6. The technician knows his own availability; the GPS provider knows the real drive. Confirmed: the endpoint already returns both distance and duration. |
| D7 | Crash recovery via a **Reconciler sweep**, not an action outbox. | Actions are derivable from state, so there is nothing to journal. The sweep also covers .NET being briefly unavailable. |
| D8 | Over-commitment is prevented by an **eligibility matrix over existing dispatch data** (§3.5), enforced transactionally inside `Assign`. No new claim table. | The existing system already records which dispatch is assigned to whom and its status. A second copy would only drift. |
| D9 | Scope unit is the **branch** throughout — toggle, timer config, and SignalR group. | "Division" (§5) and "region" (brief) are loose synonyms for the same 46 branches. One key, one table, one cache. |
| D10 | Revoking a dead offer uses a **silent data push**, with the `409` reply path as the backstop. | Delivery is best-effort and iOS throttles silent pushes, so the server must reject a stale accept regardless. The push is the clean-UX layer on top of a guarantee that lives server-side. |

---

## 3. Data model

Owned by .NET, in SQL Server. Three new tables; eligibility reads existing data.

### 3.1 `dispatch_state` — one row per dispatch in flight

| Field | Purpose |
|---|---|
| `dispatchId` | PK |
| `branchId` | scope for the auto-dispatch toggle and timer config |
| `priority` | `Emergency` \| `High` \| `Medium` — selects `w` in the §6 formula, and drives eligibility |
| `stage` | see §4.1 |
| `candidates` | JSON array, see below |
| `ranked` | JSON array of `techId`, ordered. Computed **once** and frozen. |
| `offerCursor` | index into `ranked` of the highest-ranked technician who has been sent an offer |
| `deadlineAt` | UTC — the single next deadline. Never two timers on one dispatch. |
| `version` | monotonic int, optimistic-lock token |
| `parkedFrom` | stage to resume into when a branch toggle comes back on |
| `createdAt` / `updatedAt` | `updatedAt` drives the Reconciler sweep |

`candidates[]` element:

```
{ techId, distMi, driveMin, visits, freeMin | null, status }
```

`distMi`, `driveMin`, `visits` arrive from `GetNearestVehicles`. `freeMin` arrives from the technician's Stage-A reply.

`status` lifecycle:

```
PENDING_ETA ──► ETA_IN ────┐
     │                     ├──► OFFERED ──► ACCEPTED
     └──► NO_REPLY ────────┘              ├──► DECLINED
                                          └──► WITHDRAWN   (became ineligible / branch parked)
```

`ranked` is frozen at the end of Stage A. A withdrawal marks a candidate's status but never triggers a re-rank — this keeps the ranking explainable ("here is the shortlist, in order, computed once"), which is a stated requirement for A.

### 3.2 `dispatch_event_inbox` — the durable event log

| Field | Purpose |
|---|---|
| `id` | PK, monotonic |
| `dispatchId` | partition key for per-dispatch serialisation |
| `type` | see §4.2 |
| `payload` | JSON |
| `createdAt` | |
| `claimedBy` / `claimedAt` | worker lease; expiry lets a dead worker's claim be retaken |
| `processedAt` | null until handled |

### 3.3 `branch_config` — toggle + timers, one row per branch

```
branch_config {
  branchId             PK        -- 46 rows
  autoDispatchEnabled  bit
  etaWindowSec         int  DEFAULT 60    -- X
  cascadeIntervalSec   int  DEFAULT 30    -- K
  updatedAt
}
```

`X` and `K` are **per branch, not per priority** — an Emergency and a Medium dispatch in the same branch use the same windows. The priority lever is `w` in the ranking formula and the eligibility matrix, not the clock.

The toggle is **state, not an event**. This is what makes toggle flapping (edge case 4) a non-problem — see §4.4.

### 3.4 `dispatch_activity` — audit trail, written by .NET

Append-only log of `(dispatchI

d, event, fromStage, toStage, detail, at)`. Written in the same handler that persists state, and the payload of the SignalR broadcast. Free byproduct of D5; also the debugging record when a dispatch goes wrong.

### 3.5 Eligibility — derived, not stored

A technician's capacity for new work is read from the **existing dispatch table**. Nothing new is persisted.

`free_i` is *"time to become available from the current job"* — the technician is never asked to estimate work he has queued, because he cannot reliably do so. Instead, capacity is a matrix over what he already holds:

| Technician's pending work | New dispatch = **Emergency** | New dispatch = High / Medium |
|---|:---:|:---:|
| nothing pending | ✅ eligible | ✅ eligible |
| 1 non-emergency pending | ✅ eligible | ❌ |
| any emergency pending | ❌ | ❌ |

*Pending* = assigned but not yet started, per the existing status model.

Consequences:

- **Max pending depth is 2** (one non-emergency + one emergency). It falls out of the matrix — there is no `N` to configure.
- **The technician chooses his own sequence.** The system never dictates order, so it never has to model job durations or inter-job travel. This is what removes the queue-estimation problem entirely.
- An ineligible technician is simply skipped: cascade to the next ranked technician, escalate if the shortlist runs out.

The matrix is applied in two places:

1. **Stage A candidate filter** — advisory. Ineligible technicians never receive an ETA request.
2. **Accept time, inside `Assign`** — authoritative. Eligibility can go stale between the two (he accepted something else meanwhile), which returns `409` and is handled by the existing `WITHDRAWN` + cascade path.

**Required index:** `dispatch(assignedTech, status)` — the accept-time guard takes a range lock on this.

**Implementation note for the .NET team:** confirm which existing status values mean "assigned but not yet started."

---

## 4. State machine

### 4.1 States

| State | Meaning | Terminal |
|---|---|---|
| `PENDING_ADMIT` | queued, waiting for an ActionExecutor slot to run `FETCH_CANDIDATES` | |
| `COLLECTING_ETA` | Stage A — ETA requests pushed, window open | |
| `OFFERING` | Stage B — one or more live accept/reject offers outstanding | |
| `PARKED` | branch toggle went off mid-flight | |
| `ASSIGNED` | technician accepted | ✔ |
| `ESCALATED` | shortlist exhausted or no eligible candidates — dispatcher column | ✔ |
| `CANCELLED` | job withdrawn or manually assigned upstream | ✔ |

There is deliberately **no `RANKING` state**. `GetNearestVehicles` already returns visits and drive duration, so ranking needs no I/O — it is a pure function executed inside the `ETA_WINDOW_EXPIRED` transition.

Terminal states ignore all events (log + broadcast a `late_event` marker). This is what makes at-least-once event delivery safe.

### 4.2 Events

| Event | Origin |
|---|---|
| `ADMIT` | ActionExecutor granted a slot |
| `ETA_SUBMITTED(techId, freeMin)` | .NET ← mobile app |
| `ETA_WINDOW_EXPIRED` | TimerTicker |
| `OFFER_ACCEPTED(techId)` | .NET ← mobile app |
| `OFFER_DECLINED(techId)` | .NET ← mobile app |
| `CASCADE_TICK` | TimerTicker |
| `TECH_WITHDRAWN(techId)` | .NET, transactionally on another dispatch's assign |
| `DISPATCH_CANCELLED` | .NET |

Branch enable/disable are **not events** — see §4.4.

### 4.3 Transitions

`X` and `K` below are read from `branch_config` for this dispatch's branch.

```
PENDING_ADMIT --ADMIT--> COLLECTING_ETA
  actions: FETCH_CANDIDATES            # already filtered by the §3.5 matrix
           if candidates empty -> ESCALATED { API_ESCALATE(reason=no_eligible_candidates) }
           PUSH_ETA_REQUEST(all candidates)
           ARM_TIMER(now + X)

COLLECTING_ETA --ETA_SUBMITTED--> COLLECTING_ETA
  guard:   techId in candidates AND status == PENDING_ETA AND round matches
           (else: ignore — makes redelivery and stale replies harmless)
  actions: candidate.freeMin = freeMin; candidate.status = ETA_IN
           if no PENDING_ETA remain -> self-fire ETA_WINDOW_EXPIRED   # early exit

COLLECTING_ETA --ETA_WINDOW_EXPIRED--> OFFERING
  actions: remaining PENDING_ETA -> NO_REPLY
           ranked = Ranker.rank(candidates, priority)     # PURE, frozen from here
           if ranked empty -> ESCALATED { API_ESCALATE(reason=no_eta_replies) }
           offerCursor = 0
           PUSH_OFFER(ranked[0]); ARM_TIMER(now + K)

OFFERING --CASCADE_TICK--> OFFERING
  actions: offerCursor += 1
           if offerCursor >= len(ranked)
               -> ESCALATED { API_ESCALATE(reason=exhausted), REVOKE_OFFER(all OFFERED) }
           PUSH_OFFER(ranked[offerCursor]); ARM_TIMER(now + K)
           # earlier offers STAY LIVE — required behaviour, not a bug

OFFERING --OFFER_ACCEPTED--> ASSIGNED
  guard:   candidate.status == OFFERED
  actions: API_ASSIGN(techId)                    # authoritative — may return 409
           on 409 (already_assigned | not_eligible):
                candidate -> WITHDRAWN; remain OFFERING; re-evaluate
           on 200: REVOKE_OFFER(all other OFFERED); CLEAR_TIMER
                   (.NET has already written the selective TECH_WITHDRAWN fan-out)

OFFERING --OFFER_DECLINED--> OFFERING
  actions: candidate -> DECLINED
           if every OFFERED is now DECLINED:
               if offerCursor is last -> ESCALATED
               else -> self-fire CASCADE_TICK        # don't burn the remaining K seconds

COLLECTING_ETA | OFFERING --TECH_WITHDRAWN--> same state
  actions: candidate -> WITHDRAWN
           if he held the only live offer -> self-fire CASCADE_TICK

any non-terminal --DISPATCH_CANCELLED--> CANCELLED
  actions: CLEAR_TIMER; REVOKE_OFFER(all OFFERED)

PARKED --(toggle back on, see §4.4)--> parkedFrom
  actions: COLLECTING_ETA -> ARM_TIMER(now + X); PUSH_ETA_REQUEST(PENDING_ETA only)
           OFFERING       -> ARM_TIMER(now + K); PUSH_OFFER(ranked[offerCursor])
           # ranked stays frozen — no re-rank, no re-fetch
```

Every transition ends with `persist(state', expectVersion)`, and .NET broadcasts to the board from inside that call (D5).

### 4.4 The toggle is a guard, not an event

Every event handler begins:

```
st  = StateStore.load(dispatchId)
cfg = BranchConfigCache.get(st.branchId)          # enabled + X + K

if not cfg.enabled and st.stage not in TERMINAL:
    park(st)                 # parkedFrom = stage; CLEAR_TIMER; REVOKE_OFFER(live)
    return

if cfg.enabled and st.stage == PARKED:
    resume(st, cfg)          # re-arm from parkedFrom, then fall through
```

Because the toggle is read from state on every event rather than delivered as a message, a dispatcher can flip a branch on and off arbitrarily fast and the worker simply reads whatever is current. There is no ordering to get wrong and no message to lose. Redis nudging only affects *how quickly* a flip is noticed (bounded by the cache TTL, ~2s).

Branches are independent by construction: parking is per-dispatch, keyed on that dispatch's `branchId`. Dispatches in enabled branches keep flowing through the same worker with no special handling.

---

## 5. Components

All worker-side. N stateless replicas, no leader, no sharding — work is distributed by inbox claim leases.

```
DispatchWorker
├── EventSource         nudge (Redis XREADGROUP, 1s block) ∥ inbox poll (1.5s) → one stream
├── TimerTicker         DueDeadlines(now) → ETA_WINDOW_EXPIRED / CASCADE_TICK
├── BranchConfigCache   branch_config, ~2s TTL, nudge-invalidated
├── DispatchLock        Redis lock keyed on dispatchId; degrades to CAS-only
├── StateStore          load / persist(CAS) via .NET; Redis hot copy
├── StateMachine        advance(state, event, cfg, now) → (state', actions)   ← PURE
├── Ranker              rank(candidates, priority) → ordered[]                ← PURE
├── ActionExecutor      semaphore + token bucket + retry/backoff + circuit breaker
│   ├── FieldJetXClient   .NET calls
│   └── PushClient        SNS publish — NOT gated (separate backend)
└── Reconciler          30s sweep, heals dropped actions
```

### 5.1 Contracts

Signatures only — no bodies. Bodies land in implementation tickets.

```python
# ---------- PURE CORE: no I/O, no clock, no network ----------

class StateMachine:
    def advance(self, state: DispatchState, event: Event,
                cfg: BranchConfig, now: datetime
                ) -> tuple[DispatchState, list[Action]]: ...
    def park(self, state: DispatchState
             ) -> tuple[DispatchState, list[Action]]: ...
    def resume(self, state: DispatchState, cfg: BranchConfig, now: datetime
               ) -> tuple[DispatchState, list[Action]]: ...

class Ranker:
    def rank(self, candidates: list[Candidate], priority: Priority
             ) -> list[TechId]: ...
    def _eta(self, c: Candidate) -> float: ...            # free_i + driveMin_i
    def _weight(self, priority: Priority) -> float: ...   # w per §6 table
    def _normalise(self, values: list[float]) -> list[float]: ...  # min-max, tie-safe


# ---------- I/O EDGE ----------

class EventSource:
    def next(self, timeout_ms: int) -> Event | None: ...
    def ack(self, event: Event) -> None: ...
    def _from_nudge(self) -> Event | None: ...
    def _from_inbox_poll(self) -> Event | None: ...

class TimerTicker:
    def tick(self) -> list[Event]: ...
    def arm(self, dispatch_id: DispatchId, at: datetime) -> None: ...
    def clear(self, dispatch_id: DispatchId) -> None: ...

class BranchConfigCache:
    def get(self, branch_id: BranchId) -> BranchConfig: ...   # enabled, X, K
    def invalidate(self, branch_id: BranchId) -> None: ...

class DispatchLock:
    # Context manager. Yields a LockHandle when the Redis lock is held, or
    # None when Redis is unreachable — it never raises and never blocks the
    # caller, because CAS in StateStore.persist carries correctness on its own.
    @contextmanager
    def guard(self, dispatch_id: DispatchId, ttl_s: int
              ) -> Iterator[LockHandle | None]: ...

class StateStore:
    def load(self, dispatch_id: DispatchId) -> DispatchState: ...
    def persist(self, state: DispatchState, expect_version: int,
                caused_by: Event) -> PersistResult: ...   # CONFLICT | OK(new_version)

class ActionExecutor:
    def submit(self, action: Action) -> None: ...
    def _acquire_slot(self, kind: ActionKind) -> Slot: ...  # assign gets reserved slice
    def breaker_state(self) -> BreakerState: ...

class FieldJetXClient:
    def get_nearest_vehicles(self, dispatch_id: DispatchId) -> list[Candidate]: ...
    def save_state(self, state: DispatchState, expect_version: int,
                   caused_by: Event) -> PersistResult: ...
    def assign(self, dispatch_id: DispatchId, tech_id: TechId) -> AssignResult: ...
    def escalate(self, dispatch_id: DispatchId, reason: str) -> None: ...
    def claim_inbox_events(self, worker_id: str, limit: int) -> list[Event]: ...
    def due_deadlines(self, now: datetime) -> list[Event]: ...
    def mark_processed(self, event_ids: list[int]) -> None: ...
    def branch_configs(self) -> list[BranchConfig]: ...

class PushClient:
    def push_eta_request(self, dispatch_id, techs: list[TechId], round: int) -> None: ...
    def push_offer(self, dispatch_id, tech: TechId, round: int) -> None: ...
    def revoke_offer(self, dispatch_id, techs: list[TechId], round: int) -> None: ...
        # silent data-only push (content-available / FCM data message)

class Reconciler:
    def sweep(self) -> list[Action]: ...
```

### 5.2 The main loop

```python
while running:
    ev = event_source.next(timeout_ms=1000)
    if ev is None:
        continue

    with dispatch_lock.guard(ev.dispatch_id, ttl_s=30):   # yields None if Redis is down
        st = state_store.load(ev.dispatch_id)
        loaded_version = st.version          # capture BEFORE advance — this is the CAS token
        cfg = branch_config_cache.get(st.branch_id)

        if not cfg.enabled and st.stage not in TERMINAL:
            st, actions = state_machine.park(st)
        elif cfg.enabled and st.stage == PARKED:
            st, actions = state_machine.resume(st, cfg, now())
            st, more = state_machine.advance(st, ev, cfg, now())
            actions += more
        else:
            st, actions = state_machine.advance(st, ev, cfg, now())

        result = state_store.persist(st, expect_version=loaded_version, caused_by=ev)
        if result.is_conflict:
            continue                      # another replica won; event stays unacked, retried

        for a in actions:
            action_executor.submit(a)

        event_source.ack(ev)
```

Note the ordering: **persist before emit**. A crash between the two loses actions, which the Reconciler heals (§5.4). A crash between emit and ack causes redelivery, which transition guards make harmless.

Lock TTL must exceed `max(X, K)` for the branch, so a lock is never lost mid-flight — the timeout rule already stated in §5 of the HTML doc.

### 5.3 ActionExecutor

```
semaphore(N)                # N = max concurrent .NET calls, configurable
  └── reserved slice for API_ASSIGN so accepts never starve behind a fetch burst
token_bucket(rate, burst)   # smooth bursts against the legacy tier
retry(exponential backoff + jitter) on 5xx / timeout
circuit_breaker             # trips when .NET is failing
```

When the breaker trips, the worker **stops draining `PENDING_ADMIT`** — those rows just sit, nothing is lost — but keeps handling reply and timer events for dispatches already in flight, because those need `API_ASSIGN` and a technician who tapped Accept must not be dropped.

Push (SNS) is not gated. It is a different backend and carries no risk to the legacy server.

### 5.4 Reconciler

Every 30s, sweep non-terminal dispatches whose `updatedAt` is older than one sweep interval, and re-derive the actions that state implies:

| Observed state | Healing action |
|---|---|
| `PENDING_ADMIT`, aged | re-emit `FETCH_CANDIDATES` |
| `COLLECTING_ETA`, `deadlineAt` null | re-arm timer |
| `OFFERING`, `ranked[offerCursor].status != OFFERED` | re-push that offer |
| `deadlineAt` in the past by more than one tick | fire the corresponding deadline event |

No outbox table, no journal. Actions are a function of state, so state is the only thing that has to survive.

### 5.5 Push idempotency

Every push carries `(dispatchId, techId, round, version)`. The app dedupes on that tuple, so a Reconciler re-push does not buzz the phone twice. Replies echo the tuple back, and the transition guards reject stale rounds — which is also what stops a reply to a revoked offer from resurrecting a resolved dispatch.

---

## 6. Edge cases

### 6.1 Accept atomicity — one accept, correct rejections

Two layers, and neither depends on Redis.

**Within one dispatch.** Multiple technicians can hold live offers simultaneously — the cascade does not revoke earlier offers, by design. Two simultaneous accepts both produce `OFFER_ACCEPTED` events. Each is handled under the per-dispatch lock, and `persist` uses CAS on `version`. The first wins and reaches `ASSIGNED`. The second finds `stage == ASSIGNED`, a terminal state, and is ignored.

**Across dispatches.** `API_ASSIGN` on the .NET side is the sole authority, in one transaction:

```sql
BEGIN TRAN
  -- 1. eligibility per the §3.5 matrix, against existing dispatch data
  IF EXISTS (SELECT 1 FROM dispatch WITH (UPDLOCK, HOLDLOCK)
             WHERE assignedTech = @t
               AND status = <assigned-not-yet-started>
               AND ( priority = 'Emergency'      -- any pending emergency blocks all
                     OR @p <> 'Emergency' ))     -- non-emergency blocks non-emergency
      ROLLBACK; RETURN 409 not_eligible

  -- 2. per-dispatch guard
  UPDATE dispatch SET assignedTech = @t, status = <assigned>
   WHERE dispatchId = @d AND assignedTech IS NULL
  IF @@ROWCOUNT = 0  ROLLBACK; RETURN 409 already_assigned

  -- 3. selective fan-out, same transaction
  INSERT dispatch_event_inbox (dispatchId, type, payload)
  SELECT dispatchId, 'TECH_WITHDRAWN', @t
    FROM dispatch_state
   WHERE stage = 'OFFERING'
     AND <@t is OFFERED in candidates>
     AND ( @p = 'Emergency'                 -- accepted emergency -> withdraw everywhere
           OR priority <> 'Emergency' )     -- accepted routine  -> keep emergency offers
COMMIT
```

`UPDLOCK, HOLDLOCK` on `dispatch(assignedTech, status)` takes a range lock keyed on the technician, so two concurrent accepts cannot both pass step 1. Because step 3 shares the transaction, the withdrawal fan-out cannot be lost to a worker or Redis failure.

**The fan-out is selective**, following directly from the matrix:

| He accepts | Other offers withdrawn | Offers that stay live |
|---|---|---|
| an Emergency | all of them | none |
| a non-Emergency | other non-Emergency only | Emergency offers |

A technician who takes a routine job stays reachable for the emergency two blocks away — that is the slot the matrix deliberately reserves.

A worker receiving `409` marks that candidate `WITHDRAWN`, stays in `OFFERING`, and re-evaluates.

### 6.2 Race conditions generally

Three independent guards, in order of cost:

1. **Per-dispatch lock** (Redis) — one writer at a time. Cheap, and the common case.
2. **CAS on `version`** — the actual correctness guarantee. Holds even with no lock at all, which is why Redis being down is survivable.
3. **Transition guards** — every transition validates `(techId, status, round)` before acting, so redelivered, stale, and out-of-order events are inert.

Cross-dispatch races are handled separately by the range lock in §6.1.

### 6.3 Branch toggle off mid-flight

Covered by §4.4. The toggle is read at the top of every handler, so a disabled branch parks its dispatches while other branches continue through the same worker untouched. Parking revokes live offers so technicians' phones don't hold dead windows.

A dispatch already `ASSIGNED` or `ESCALATED` is terminal and unaffected — turning a branch off does not retroactively undo assignments.

### 6.4 Toggle flapping on ↔ off

A non-problem by design. There is no toggle *message* to arrive out of order or get lost — only `branch_config.autoDispatchEnabled`, read fresh (within the ~2s cache TTL) on every event. Flip it 20 times a second and the worker reads whatever is current at the moment it happens to handle an event. `parkedFrom` preserves the exact stage, `ranked` stays frozen, and resume re-arms the timer — so a flap costs at most one re-pushed offer, deduped by §5.5.

### 6.5 Redis down

| Redis role | Degradation |
|---|---|
| nudge stream (new dispatches, replies) | inbox poll at 1.5s picks them up — the poll loop **always runs**, so this path is exercised in production daily and cannot rot |
| timer index | `deadlineAt` is a SQL column; `DueDeadlines` is both the primary and the fallback — no separate code path exists |
| per-dispatch lock | `guard` yields `None`; CAS carries correctness |
| hot state copy | read-through to .NET, slower |
| branch-config invalidation | falls back to TTL expiry, ~2s |
| board fan-out | unaffected — SignalR is .NET-side (D5) |

Net effect: auto-dispatch keeps working, latency moves from ~50ms to ~1.5s per transition. Nothing is lost and nothing needs a human.

### 6.6 WebSocket streaming to the dispatch board

Per D5. The worker's existing `save_state` call is the trigger: .NET writes `dispatch_state`, appends `dispatch_activity`, and pushes to the SignalR group for that `branchId` — all in one handler. The worker does not know a board exists.

Board reconnect: `GET /api/dispatch/BoardSnapshot(branchId)` for current state plus a tail of `dispatch_activity`, then resume the socket.

**Known future step:** if .NET ever runs on more than one instance, SignalR needs a Redis backplane so a broadcast from instance 1 reaches a browser connected to instance 2. One config line, and Redis is already provisioned. Not needed at current scale (one EC2 host, 46 branches, a few dozen concurrent dispatchers).

---

## 7. Changes required to existing documents

| File | Change |
|---|---|
| `sections/06.html` | Delete Step A (`travel_i = dist_i / AVG_SPEED * 60`). Replace with `eta_i = free_i + driveMin_i`, where `free_i` is technician-submitted availability **from his current job** and `driveMin_i` is GPS drive duration from `GetNearestVehicles`. Drop `AVG_SPEED` from the inputs list. Add the §3.5 eligibility matrix as a hard pre-ranking gate, alongside the existing skill-gate note. |
| `sections/02.html` | "ECS workers read/write SQL Server" → workers reach SQL **only** through the .NET Microservices API. Redis reclassified from durable queue to nudge/cache. Add the SignalR board path. |
| `sections/04.html` | Dispatch workers: "Scale 0–1 on toggle" → **0 when all branches off, min 1 when any branch on, scale on inbox depth**. One replica is a single point of failure for the TimerTicker, and stateless replicas remove any reason to cap at 1. Redis note "must not evict" still holds for the nudge stream but is no longer correctness-critical. |
| `sections/05.html` | Replace the `BLPOP`-blocking SNS round-trip (steps 3–5) with the inbox + nudge path. Add park/resume to the assignment loop. Rename "division" → **branch** throughout. |
| `sections/07.html` | Add `dispatch_state`, `dispatch_event_inbox`, `branch_config`, `dispatch_activity`, and the `dispatch(assignedTech, status)` index. |
| `sections/08.html` | Add `GetNearestVehicles`, `SaveState`, `Assign`, `Escalate`, `ClaimInboxEvents`, `DueDeadlines`, `MarkProcessed`, `BoardSnapshot`, `BranchConfigs`. |
| `sections/11.html` | Add the Redis-down degradation table (§6.5) and the circuit-breaker behaviour (§5.3). |
| `CLAUDE.md` | The "Azure-only except AWS SQL Server" description no longer matches `sections/02.html`/`04.html`, which now place all non-AI infrastructure on AWS with only the AI stack on Azure. Reconcile. |

---

## 8. Resolved blockers

All five original blockers are closed. Recorded here because each one changed the design.

| # | Question | Resolution |
|---|---|---|
| B1 | Does `GetNearestVehicles` return drive duration? | **Yes** — returns `distMi` and `driveMin`. No .NET change needed; the "expose duration" ticket was dropped and `A-02` unblocked. |
| B2 | Values for X and K | **Per branch, not per priority.** Defaults X=60s, K=30s in `branch_config`, overridable per branch. |
| B3 | Silent revoke push? | **Yes** — silent data push (`content-available` / FCM data message), with the `409` reply path as the required backstop. |
| B4 | Region vs division vs branch | **Branch** — one unit for toggle, timers, and SignalR group. `regionId` and "division" removed from all docs. |
| B5 | Atomic protection against double-accept | **Eligibility matrix over existing dispatch data** (§3.5), enforced by `UPDLOCK, HOLDLOCK` inside the `Assign` transaction. No new claim table — the existing system is already the source of truth. |

Remaining implementation notes (not blockers):

- Confirm which existing dispatch status values mean "assigned but not yet started" (§3.5).
- Add index `dispatch(assignedTech, status)` before the accept-time guard ships.
- iOS throttles silent pushes; the `409` path must be tested independently of push delivery.

---

## 9. Implementation tickets

High-level only. Each is independently testable; the pure-core tickets need no infrastructure at all.

### Phase 1 — pure core (no infrastructure, no dependencies, unblocked today)

| ID | Ticket | Notes |
|---|---|---|
| A-01 | Define `DispatchState`, `Candidate`, `Event`, `Action`, `BranchConfig` types + serialisation | Frozen dataclasses; the contract everything else codes against |
| A-02 | Implement `Ranker.rank` | §6 formula with `eta_i = free_i + driveMin_i`. Tie-safe min-max normalisation (all-equal → flat term). |
| A-03 | Implement `StateMachine.advance` | Full transition table §4.3. No I/O, no clock reads — `now` and `cfg` are parameters. |
| A-04 | Implement `StateMachine.park` / `resume` | `parkedFrom` handling, offer revocation, timer re-arm from branch config |
| A-05 | Unit-test suite for the pure core | One test per row of §4.3 plus all six edge cases from §6, driven by hand-built state structs. No mocks, no containers. |

### Phase 2 — .NET side

| ID | Ticket | Notes |
|---|---|---|
| A-06 | Migrations: `dispatch_state`, `dispatch_event_inbox`, `branch_config`, `dispatch_activity` | Indexes: inbox on `(processedAt, claimedAt)`, state on `(stage, deadlineAt)` and `(stage, updatedAt)` |
| A-07 | Index `dispatch(assignedTech, status)` + confirm the "assigned-not-started" status values | Prerequisite for A-09's range lock |
| A-08 | `SaveState` endpoint: CAS update + activity append + SignalR broadcast, one handler | Returns `409` on version mismatch. This single endpoint delivers D5. |
| A-09 | `Assign` endpoint: eligibility guard + conditional assign + selective `TECH_WITHDRAWN` fan-out, **one transaction** | §6.1 SQL. The atomicity guarantee for edge case 1. Depends on A-07. |
| A-10 | `Escalate` endpoint | Moves the dispatch to the dispatcher column |
| A-11 | Inbox write path on every mobile reply + dispatch-created + cancel | SQL insert first, Redis nudge second and best-effort |
| A-12 | `ClaimInboxEvents` / `MarkProcessed` with lease + expiry | Lease expiry is what lets a dead worker's claim be retaken |
| A-13 | `DueDeadlines` endpoint | Atomic claim so concurrent replicas can't double-fire a timer |
| A-14 | SignalR hub + `BoardSnapshot` endpoint | Groups keyed on `branchId` |
| A-15 | `branch_config` CRUD + `BranchConfigs` read endpoint + nudge on change | Dispatcher toggle UI writes here |
| A-16 | Stage A candidate filter: apply the §3.5 matrix inside `GetNearestVehicles` | Ineligible technicians never get an ETA request |

### Phase 3 — worker I/O edge

| ID | Ticket | Notes |
|---|---|---|
| A-17 | `FieldJetXClient` — typed wrapper over all .NET endpoints | |
| A-18 | `EventSource` — unify nudge stream and inbox poll into one event stream | Poll loop runs unconditionally, not "on failure" |
| A-19 | `StateStore` — load/persist with CAS and Redis hot copy | Read-through when Redis absent |
| A-20 | `DispatchLock` — Redis lock yielding `None` when unavailable | Must be a clean degrade, not an exception |
| A-21 | `BranchConfigCache` — TTL cache + nudge invalidation | Supplies enabled, X, K |
| A-22 | `TimerTicker` | |
| A-23 | `ActionExecutor` — semaphore, reserved assign slice, token bucket, retry, breaker | The D3 concurrency gate |
| A-24 | `PushClient` — SNS publish with the `(dispatchId, techId, round, version)` idempotency tuple | Includes the silent revoke message |
| A-25 | Main loop wiring + graceful shutdown | Shutdown: stop pulling events, finish in-flight handlers, release claims. Because nothing sleeps, drain is seconds — no 10-minute window. |
| A-26 | `Reconciler` sweep | |

### Phase 4 — mobile

| ID | Ticket | Notes |
|---|---|---|
| A-27 | ETA-request notification + reply screen | Wording must make clear it means *current job only*. Reply carries the idempotency tuple. |
| A-28 | Accept/reject offer screen; support multiple simultaneous live offers | A technician can legitimately hold offers on several dispatches at once |
| A-29 | Silent-push handler — close an open offer window with no banner or sound | Background data messages on both APNs and FCM |
| A-30 | Handle `409 already_assigned` / `409 not_eligible` on accept | The backstop when a silent push doesn't arrive — must work standalone |
| A-31 | Dedupe pushes on `(dispatchId, techId, round, version)` | |

### Phase 5 — board and operations

| ID | Ticket | Notes |
|---|---|---|
| A-32 | Dispatch board live view — SignalR subscribe, snapshot on reconnect | |
| A-33 | Board activity feed from `dispatch_activity` | |
| A-34 | Dispatcher toggle UI + X/K override per branch | Writes `branch_config` (A-15) |
| A-35 | Metrics + alerts: inbox depth, poll-mode active, breaker state, escalation rate, time-to-assign | Poll-mode-active is the Redis-down signal |
| A-36 | Load test: 100 concurrent dispatches, verify the executor cap holds and no dispatch stalls | |
| A-37 | Chaos tests: kill Redis mid-cascade · kill a worker mid-cascade · flap a toggle during Stage B · double-accept the same technician · accept routine then emergency | Each maps to an edge case in §6; the last one verifies the selective fan-out |

### Critical path

```
A-01 ─► A-02/A-03/A-04 ─► A-05                  (pure core — start now, blocks on nothing)
A-06 ─► A-08/A-11/A-12/A-13 ─► A-17..A-26        (worker cannot start before A-08)
A-07 ─► A-09                                     (range lock needs the index)
A-15 ─► A-21, A-34                               (branch config feeds cache and UI)
```

Phase 1 is unblocked today and carries most of the design risk, so it should start first.
