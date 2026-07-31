# Auto-Dispatch Engine — Logic Specification (ClimatePros UC-A)

> **★ Standalone spec.** Written so a reader (or another LLM) with **no other context** can understand the
> engine's logic. Everything essential is inlined. Prepared by techjays · Stream 1 · 2026-07-31.
>
> **Status:** design **in progress (~70%) — NOT yet build-ready.** The contention core is sound for the
> single-dispatch / single-datastore idealization; two adversarial red-team rounds hardened it. **Latest
> decisions (2026-07-31) are folded in §11** — the §11 gate direction is now chosen (Option B), the
> reprioritize→epoch rule **resolves round-2 critical #2** (stale-offer), and the concurrency scenario rulings
> are decided. **Still open before build:** the §11 co-transactionality mechanics, the **duplicate-owner
> monitor** (round-2 critical #1), the ranking-comparator math fix, a few decisions (§11), and a **3rd
> red-team round** to confirm convergence. Two foundations remain unbuilt (§9). Access + system complexities:
> see the companion `UC-A-Access-Needed-and-System-Complexities.md`. **Labeling:** `[DECIDED]` (agreed this design cycle) · `[LOCKED]` (client/scope
> decision — do not reopen) · `[OPEN]` (undecided) · `[GROUNDED]` (verified in the live staging DB / code).
> **Provenance & deeper detail:** §14.

---

## Contents
0. TL;DR (mental model)
1. What this engine is (context)
2. The guarantee (the invariant everything serves)
3. Architecture & pipeline
4. The design spine (3 principles)
5. Mechanisms (M1–M6)
6. Domain models (priority, SLA, availability/slot, priority-aware cap, on-site, ETA)
7. Business rules & exceptions
8. Data grounding (real facts the logic depends on)
9. Integration surface & prerequisites
10. Worked examples
11. Open decisions
12. Known limitations & red-team residual
13. Glossary
14. Provenance

---

## 0. TL;DR (mental model)
FieldJetX is ClimatePros' field-service platform. A **dispatch** is a job. New jobs land in the
**Ready-for-Dispatch (RFD)** column; today a human dispatcher phones technicians one by one until someone
takes it. The **Auto-Dispatch Engine** automates that: it ranks eligible techs, offers the job to their
phones in order (a staggered cascade), and the first to **Accept** gets it.

It automates **exactly one status change — RFD → Dispatched — and only on a tech's acceptance.** Everything
else stays human. The core is **deterministic: no AI/LLM ever ranks or picks a technician.** The whole
engine exists to keep one promise: **every job ends up with exactly one technician — never two, never
zero-and-forgotten** — even under simultaneous accepts, manual overrides, crashes, and bad data.

---

## 1. What this engine is (context)

- **Platform:** FieldJetX (FJX) — .NET backend + SQL Server, an Angular web **dispatch board** (what
  dispatchers use), and a Flutter **mobile app** (what technicians use). ClimatePros runs ~900–1,000 techs
  across 46 branches; ~700 new dispatches/day.
- **Entity:** a **dispatch** (not "ticket"/"call"). It carries a customer, a location, a **priority**, an
  **SLA date/time**, and a **status** (one of ~55, e.g. Ready-for-Dispatch, Dispatched, Follow-Up).
- **Scope of automation:** the single transition **RFD → Dispatched**, on a technician accept. `[LOCKED]`
- **Design stance:** system **proposes, people decide**; deterministic core (no LLM picks a tech; AI only on
  language edges elsewhere); FieldJetX stays the system of record — the engine is a **separate service** that
  talks to FJX over its APIs, not a rewrite. `[LOCKED]`

---

## 2. The guarantee (the invariant everything serves)

1. **Exactly one owner per dispatch — ever.** Two technicians must never both be assigned one job. (The
   client calls this the single unacceptable outcome.)
2. **No job silently dropped.** Every dispatch is assigned, or escalated to a human — never lost.
3. **Deterministic & explainable.** Identical inputs → identical ranked order + identical plain-language
   reason. No AI in the decision.
4. **Fail safe.** When any input is missing or untrustworthy, hand the dispatch to the dispatcher rather
   than guess.

---

## 3. Architecture & pipeline

The engine is an event-driven pipeline. A dispatch flows through:

```
1 TRIGGER      a dispatch ENTERS an RFD (allow-listed) status
2 SCREEN       is it actually dispatchable? (skip PM/Locked; null-priority → dispatcher)
3 POOL         build the candidate techs (service-side, in-area, available, under cap)
4 RANK         order them (distance-first; emergency = speed only)  [normalization OPEN]
5 OFFER        staggered cascade of Dispatch Proposals to phones; ETA Proposals for busy techs
6 ACCEPT       the one atomic Commit gate: first accept wins → RFD → Dispatched
7 ESCALATE     cascade exhausted / no candidates / service down → living Escalated queue → dispatcher
8 STATE        all of the above is durable; reconciled against FJX on restart
```
Cross-cutting: **emergency handling**, the **priority-aware workload cap**, and **System activity**
(plain-language narration of every step, written into FJX's native per-dispatch history).

---

## 4. The design spine (3 principles) `[DECIDED]`

1. **One gate owns the truth.** A single atomic **Commit** is the *only* path that writes → Dispatched. A
   tech accepting an offer AND a dispatcher assigning by hand are **both just callers** of that gate. Offers,
   push, the cascade, the UI — none of them assign; they only *propose*.
2. **Fail safe to the dispatcher** whenever an input is missing/untrustworthy.
3. **Durable & reconciled.** All in-flight state lives in the engine's own DB; on restart it **reconciles
   against FieldJetX before acting.**

---

## 5. Mechanisms

### 5.1 M1 — The Commit gate (the heart) `[DECIDED]`
The single authoritative assignment operation. Implemented as **one server-side FieldJetX proc/transaction**
(the client's P2 change, §9) because the writes span two tables and must be atomic.

**Input (a claim):** `(dispatchId D, techId T, offerToken, expectedStatusId, slotKey S, actor, idempotencyKey)`.
`slotKey S` is **pinned when the offer was issued** (so urgency drift mid-cascade can't swap it).

**Checks — all inside one transaction:**
1. **Identity** — `offerToken` valid + single-use + `token.subject == T` (blocks impersonation). Dispatcher-force uses the dispatcher's auth.
2. **Idempotency** — if `idempotencyKey` already processed → return the prior result (no double write on retry).
3. **State CAS** — `D.statusId == expectedStatusId` AND still an allow-listed RFD status. *(Never a `tech IS NULL` check — 6.3% of RFD dispatches legitimately already carry a tech from re-entries.)*
4. **Slot-free** — T's cap-slot S is unoccupied, checked against **live `DispatchAssignments`** (the source of truth), not just the engine ledger.
5. **Cherry-pick guard** — T has no unresolved emergency offer this claim would jump. **Server-side, in the gate** (not on the phone).

**On success → commit atomically:** INSERT the assignment row · flip `D` RFD → Dispatched · occupy slot S ·
persist the idempotency key + result · emit an "assigned" event.

**Returns:** `Accepted` · `AlreadyTaken` (lost the race / no longer RFD) · `Blocked` (cherry-pick/emergency
precedence) · `Error`. **First commit wins**; the engine then withdraws all other live offers on D **and**
all of T's other same-slot offers. A missed withdrawal-push cannot cause harm — a late tap just fails check #3.

**Manual assignment / force-assign** is the *same* gate with `actor = dispatcher-force`; it wins simply by
committing (the dispatcher can act directly without waiting for the cascade). Exactly one of {manual, a
racing accept} can commit — no "two owners" state is representable.

### 5.2 M2 — Cap-slot ledger + availability model `[DECIDED]`
A tech holds at most **1 ACTIVE** job (on site now — proven by his **check-in**) **+ 1 UPCOMING** (next, with
a committed ETA). See §6.3 for the full model. Slots are occupied on Commit and released on a **positive
completion signal** (§6.3), reconcilable against live `DispatchAssignments`.

### 5.3 M3 — Durable state + reconcile-on-restart `[DECIDED]`
Cascades, ranked candidates, offers + timestamps, deadlines, and slot occupancy are **DB rows, never memory.**
On restart: rehydrate every timer, and **before re-offering anything, reconcile** each in-flight dispatch
against FJX's current status (already assigned → close the cascade; still RFD → re-arm). Rebuild slot
occupancy from live `DispatchAssignments`.

### 5.4 M4 — Front door: trigger, screen, dispatch-hours `[DECIDED]`
- **Trigger:** fires when a dispatch **enters** a status on the per-company **RFD allow-list of status GUIDs**
  (config, never hard-coded). A **drift detector** flags any RFD-shaped status *not* on the list (alerts, never silently drops).
- **Screen (fail-safe):** skip **PM** and **Locked/Scheduled** priorities; **null-priority → route to dispatcher**;
  approval/hold flags → dispatcher. When unsure, escalate — never guess.
- **Dispatch-hours window:** per area; **only emergencies auto-dispatch 24-7**; non-emergencies arriving
  off-hours are queued and **released rate-limited (SLA-ordered) at window-open** (avoids a morning stampede).

### 5.5 M5 — Living escalation `[DECIDED]`
Escalated dispatches go to a queue that is **aged + alerted** (ordered urgency-mode → SLA-remaining → age) so
nothing rots. Distinguishes **structural-empty** (no techs in the region — a config/coverage problem) from
**transient-empty** (all busy — retry-able). Triggers: cascade exhausted, no eligible candidates, or
push/FJX unavailable.

### 5.6 M6 — Ranking `[DECIDED, except normalization = OPEN]`
- **Coordinate-integrity + freshness gate:** reject null/0/US-centroid-sentinel/stale coords and **check-out
  stamps** (a tech who checked *out* of a site is not *at* it); never fabricate distance — route the job or
  drop the tech from distance-ranking with a marker. Applied to **both** the destination and the tech-origin.
- **Order:** **distance-first** (drive-time) is the primary sort; **site familiarity (prior visits) is a
  tie-breaker only**, among near-equidistant techs. This is the client's explicit rule (Jun-30): *priority
  does NOT reweight the sort.*
- **Emergency:** ranked on **pure speed** (soonest arrival), plus a **seniority floor** — a store-down should
  not go to an apprentice (feasible: `Person.SkillRating` is ~97% populated).
- **Deterministic:** stable final tie-break (stable id); no NaN on a single-candidate pool.
- **`[OPEN]` normalization method** (ratio-to-best vs min-max) — Naveen + Kiriti's call; built behind a
  pluggable interface; neither presented as final.
- **Not a ranker:** FJX's `GetDispatchRankOrders` is a static SLA picklist, **not** a technician ranker — the
  engine's ranking is net-new.

---

## 6. Domain models

### 6.1 Priority → band `[GROUNDED]`
Each dispatch carries a **priorityId** → a per-company `dbo.Priority` row with a **Color** and a name. Colour
== label (one dimension). ClimatePros (company `c12d7f16`) uses these 8 (by real usage across ~1.9M dispatches):

| Priority | Colour | ~Uses | Band |
|---|---|---|---|
| Normal | 🟢 green | 567k | **Low / baseline** |
| **Overtime Approved** | 🟡 yellow | 533k | **Emergency** (2–4h on site) |
| High | 🔴 red | 483k | **High** (~within a day) |
| PM | 🔵 blue | 132k | **out of scope** (skip) |
| Hot Parts – ASAP | 🩵 teal | 29k | flag ☐ |
| Locked – Scheduled | ⬛ black | 21k | skip ☐ |
| Special Equipment | 🟣 purple | 5k | route/skill ☐ |
| Warranty (Hot) | 🩷 magenta | 1.8k | commercial ☐ |
| _(null / blank)_ | — | ~89k | **→ dispatcher (fail-safe)** ☐ |

- **Emergency is a priority value (yellow / "Overtime Approved"), not a separate label.** Confirmed by the
  client (yellow = emergency = 2–4h) and by the data.
- The mapping is **editable config**, not hard-coded (priority IDs/colours are the client's own settings).
- **Rule:** the engine reads the priority as given; it does **not** classify or re-classify urgency `[LOCKED]`.

### 6.2 SLA / severity `[GROUNDED]`
- The client's severity is a **3-colour** scheme: **yellow = emergency (2–4h) > red = within a day > green =
  2+ days.** SLA windows are **per-customer, contract-driven** (e.g. Target 2h, Jewel ~4h; penalties for misses).
- A per-dispatch SLA clock exists (`Dispatch.SLADate` + `SLATime`, populated) but its time semantics are messy
  → **Phase 1 ranks by the priority label, not the SLA clock.** SLA time may be used later for tiebreak/pacing.
- The "1–5" scale seen elsewhere is the **technician skill rating**, NOT an SLA level.

### 6.3 Availability & slot model `[DECIDED]`
- **1 ACTIVE + 1 UPCOMING.** Active = the job he's checked in to (on site now). Upcoming = the next job, with
  a committed ETA.
- **Why exactly 1 upcoming:** the ETA forces it. A tech can only give a believable ETA for the job he can
  currently assess; he can't ETA a job-after-next while still on the current one, so he can't be *ranked* for
  a 3rd. The cap falls out of the ETA mechanism.
- **Flow:** on active job 1, job 2 arrives → **push the tech for an ETA** → rank uses ETA + travel → he wins →
  job 2 = upcoming (now full) → a 3rd job is **not** offered to him.
- **Release / re-enter pool:** he **changes the dispatch status** (Completed / Needs Parts / …) → active
  clears → upcoming rolls into active → **upcoming slot opens → he re-enters the pool.** *This status-change
  is the completion signal* (the engine listens for it — same mechanism as the RFD trigger).
- **ETA delivery:** a **push notification** to the tech's mobile.
- ☐ **Missed-signal fallback:** if the tech forgets to mark status, his slot never clears. Proposed net: his
  **check-in at the next site implies the prior job is done** + a dispatcher nudge (not a blind timer).
- ☐ **"Needs Parts" frees the tech** (he leaves the site; the job peels to the parts/follow-up track, out of
  Phase 1) — assumed, needs confirm.

### 6.4 Priority-aware cap `[DECIDED / LOCKED]`
The cap is priority-sensitive, not a flat count:

| Incoming | Goes to a "full" tech? | Effect |
|---|---|---|
| **Emergency** (yellow) | **Yes — ignores the cap** | offered to whoever arrives soonest; displaced **low** work reorders/defers |
| **High / Normal** | **No** | this is what the 1-active-+-1-upcoming cap protects |
| **Low** (24–48h window) | **Yes — beyond the cap** | flexible; first to be bumped when an emergency lands |

- **Emergency vs a tech full of LOW work:** still push for ETA; if fastest, assign; his low jobs reorder/defer.
  His ETA ≈ travel time (he can drop the low job). *(scope Rule 6 `[LOCKED]`.)*
- **Emergency vs a tech already on an EMERGENCY: NO stacking** — he's excluded from a 2nd emergency; it goes to
  the next-fastest non-emergency-committed tech, else the dispatcher (so emergency B never waits hours behind
  emergency A). *(scope Rule 7 `[LOCKED]`, confirmed 2026-07-31.)*

### 6.5 On-site direct offer (Rule 10) `[LOCKED]`
If a tech is **currently on site** at the customer location (a **fresh, active check-in** — not a check-out
stamp) and a new job comes in for that **same location**, offer it **directly to that tech only, no cascade**
(arrival ≈ 0). Still an **offer through the Commit gate** (one-tap); if he declines / doesn't respond in a
short window → fall back to the normal cascade. If his location is stale or he's checked out → treat as NOT
on-site → normal cascade. **Distinct from same-site batching** (grouping several jobs at one site), which is
Phase 2.

### 6.6 ETA & Dispatch Proposals `[LOCKED]`
- **Dispatch Proposal:** the ranked, one-tap job offer sent to a tech's phone. Staggered down the ranked list
  (higher ranks get a head start); first-accept-wins; every other proposal withdrawn on accept.
- **ETA Proposal:** a push asking a *busy* tech "how long until you're free?"; the answer feeds ranking. No
  answer within the window → treated unavailable for that dispatch.
- Both require the **push channel** (P1, §9).

---

## 7. Business rules & exceptions (from scope §5) `[LOCKED]`
**Rules:** (1) one automated status change only; (2) act on RFD as classified by ClimatePros; (3) urgency =
the priority already on the dispatch, never inferred; (4) shortlist = service-side + in-area + available +
under cap; (5) rank distance-first, familiarity as tiebreak (method OPEN, no AI); (6) workload cap 1 active +
1 upcoming, emergencies override, low may exceed; (7) emergencies to fastest, never stacked; (8) ETA Proposal
mechanics; (9) staggered Dispatch Proposal, first-accept-wins; (10) on-site direct offer; (11) System activity
narration; (12) dispatcher on/off per board ("area" = a dispatcher's board), config without redeploy.

**Exceptions:** E1 two accepts → one wins (Commit gate); E2 manual assign pre-empts, withdraws offers; E3 no
response → advance; E4 cancel/hold/reprioritize/merge → withdraw + re-evaluate (cancellation beats a tie);
E5 dispatcher can withdraw/reassign anytime; E6 push/FJX down → fall back to manual, in-flight state resumes;
E7 tech loses connectivity → advances after window; E8 toggle off mid-cascade → in-flight completes/expires.

**Out of scope (Phase 1):** classifying urgency; eligibility screening (client keeps junk out of RFD); all
statuses except RFD; same-site batching; skill/seniority ranking *(but see §11 — data supports an emergency
skill floor)*; callback auto-routing; after-hours non-emergency; helper sourcing; reordering a tech's day.

---

## 8. Data grounding (real facts the logic depends on) `[GROUNDED — staging DB / code]`
- **`Dispatch` has NO PersonId** — the assigned tech is a **separate `DispatchAssignments` row**. So "accept"
  is a multi-write (assignment + status), which is why the Commit gate must be one atomic proc.
- **RFD status GUID** = `1248C177-ED7A-4AFE-A0B9-22B304956F37`; **Dispatched** = `C8F20969-E59B-4375-8060-2472DB095399`.
- **~89k dispatches have null priority.** **6.3%** of RFD dispatches already carry a tech (re-entries).
- **Location data is weak:** live GPS/Azuga feed empty in staging; only ~⅓ of check-ins fresh; ~28% of
  check-in coords null/0/sentinel; a **check-out** (Type=3) stamp sits at a site the tech has left.
- **`Person.SkillRating` (1–5) is ~97% populated** → an emergency skill floor is feasible (contradicts the
  earlier "skill data absent" assumption, which referred to a different, sparse table).
- **Familiarity** must aggregate over a **canonical store key** — ~980 physical stores are split across ~2,176
  location IDs, so naive per-location visit counts miscount.
- ClimatePros is a **single company** (`c12d7f16`, "Climate Pros LLC", ~1.86M of ~1.9M dispatches); its 46
  branches share one priority set → **one label→band mapping.**

---

## 9. Integration surface & prerequisites

**Endpoints the engine uses (FieldJetX):**
| Purpose | Endpoint | Note |
|---|---|---|
| RFD column / board feed | `GET DispatchBoard/GetDispatchesByFilter` (statusId = RFD GUID) | how RFD is read today |
| Nearest techs + drive-time | `GET Dispatch/GetNearestVehicles?lat,lng,radius,withInTime,locationId` | Azuga-backed; data-readiness caveat |
| Dispatch detail | `GET Dispatch/GetDispatchQV/{id}`, `GetAdditionalDispatchDataQV/{id}` | |
| Assignable techs | `GET Dispatch/GetAssignableTechsForFldSvcSupQV?PersonId` | |
| Tech last position | `GET Dispatch/CheckIn/History/...` | ~⅓ fresh |
| **The write** (commit) | `Dispatch/UpdateDispatchStatus` / `SaveDispatchAssignmentMo` | **must become the combined atomic proc — P2** |

**Prerequisites (client-owned / joint — NOT built yet; these gate the safety promise):**
- **P1 — Push channel.** Server→device push (FCM/APNs) for Dispatch/ETA Proposals + withdrawals. The app ships
  with local notifications only. Needs the client's Firebase/Apple accounts.
- **P2 — Combined atomic accept proc.** One FJX server-side transaction doing assignment-INSERT + status-CAS +
  idempotency together (a WHERE-guard on the status write alone is NOT enough). This is the Commit gate.
- **P3 — Completion / terminal event feed.** So slot-release fires on a positive completion signal (tech's
  status change), not a guess. Build/subscribe to a Dispatched→terminal event.

Plus: **real-time technician location** feed readiness (Azuga), the **priority→band mapping** confirmed per
company, and an **unattended engine identity** to call FJX (no service account exists today).

---

## 10. Worked examples

**A. Two techs tap Accept at the same second.** Both call the one Commit gate; it serializes them. Rivera's
lands first: D still RFD ✓, slot free ✓ → commit (D→Dispatched, occupy slot). Chen's lands a hair later: D is
now Dispatched → State CAS fails → `AlreadyTaken`; her offer is withdrawn. One job, one tech.

**B. Emergency vs a tech full of low-priority work.** Tech has low-active + low-upcoming; a yellow job lands
nearby, he's closest. Cap is overridden (emergency); we push for ETA (≈ travel, since he can drop the low
job); he wins; his low jobs reorder/defer.

**C. Emergency vs a tech already on an emergency.** Excluded (Rule 7). The 2nd emergency goes to the
next-fastest non-emergency-committed tech, else the dispatcher — it never queues behind the first.

**D. On-site.** Tech is checked in at Walmart; a new Walmart job arrives → offered directly to him, no
cascade. Declines/no response → normal cascade.

**E. Engine crashes mid-cascade.** On restart it rehydrates timers and reconciles each in-flight dispatch vs
FJX: any already Dispatched → cascade closed; still RFD → re-armed. No orphaned or double-sent jobs.

---

## 11. Open decisions `[OPEN]`
- **Ranking normalization** — ratio-to-best vs min-max (Naveen + Kiriti). Built pluggable; distance-first is the client steer.
- **Skill-floor scope reopen** — data supports an emergency `SkillRating ≥ 4` filter; client/scope call.
- **The 4 low-volume priority flags** (Hot Parts, Warranty, Special Equipment, Locked/Scheduled) + **null-priority handling** + does **yellow stay = emergency** — client confirm.
- **Availability edges** — missed-status-signal fallback; "Needs Parts frees the tech."
- **Timing values** — stagger interval, cascade ceiling, ETA window, dispatch-hours — dispatch SME.
### Recently RESOLVED (2026-07-31) — fold into the sections above
- **§11 gate authority (was OPEN) → Option B:** the **engine orchestrates** (rank/offer/cascade/slots); **FieldJetX's DATABASE holds the "one owner" invariant** via a **uniqueness constraint** (≤1 active assignment per dispatch) + a **guarded accept proc** (assignment-INSERT + status-CAS + idempotency + an **epoch/cascade-generation token**). Engine state is a reconcilable projection of FJX truth (no cross-DB 2PC). *(This reframes P2 — see §9.)*
- **Reprioritize → restart-from-scratch with a fresh epoch → RESOLVES round-2 critical #2** (a stale non-emergency offer can no longer commit an emergency): priority is locked while a dispatch is in-cascade; any change re-enters it with a new epoch, so old offers fail the CAS.
- **Concurrency scenario rulings (with client):** ties → offer to both, first-accept-wins (no system tiebreak); flooding controlled by the 1+1 cap; **cascade is additive** (stagger timeout is backend-only, earlier offers persist, multiple techs hold live offers) — *this also defuses the round-2 cherry-pick worry*; emergency+normal to one tech → send both, tech decides; same-site new job → direct **offer** (Rule 10), not auto-assign; **no senior-reserve** in Phase 1; decline → advance fast, no-response → advance after the timer; accept-then-bail → tech phones dispatcher, manual reassign (no auto-re-dispatch); gamed ETAs → reconcile-after + surface patterns (no hard gate).
- **Availability without a tech online/offline toggle** (client refuses one): infer via **board membership − proven-off (time-off/holiday) + recent-activity signal**, with **the accept itself as the final availability check**.

### Still OPEN
- **Ranking normalization** — ratio-to-best vs min-max (Naveen + Kiriti); built pluggable; distance-first is the client steer.
- **Skill-floor scope reopen** — `SkillRating` ~97% populated → an emergency `≥4` floor is feasible; client/scope call (+ define the null-rating branch).
- **The 4 low-volume priority flags** (Hot Parts, Warranty, Special Equipment, Locked/Scheduled) + **null-priority handling** + does **yellow stay = emergency** — client confirm.
- **Availability edges** — missed-status-signal fallback ("Needs Parts frees the tech" confirmed); does a **schedule/roster** exist?
- **Timing values** — stagger, cascade ceiling, ETA window, dispatch-hours (+ TZ/DST across 46 branches) — dispatch SME.
- **The 2-concurrent-jobs / one-fast-tech-takes-both fork** — accept (simplest) vs spread one-each.
- **The §11 co-transactionality mechanics** + the **duplicate-owner monitor** (round-2 critical #1, still to design).

---

## 12. Known limitations & red-team residual
The contention core (one-gate two-key CAS) is confirmed sound for a single-DB idealization. Residual risk is
concentrated in:
- **Unbuilt foundations** P1/P2/P3 — until built + tested, the safety promise is conditional.
- **Data quality** — ranking is only as good as the location/familiarity data (§8); mitigated by the
  integrity/freshness gate + fail-safe, but a live GPS feed is a net-new dependency.
- **Assurance** — one adversarial red-team round done (found + fixed 8 issues); not yet "dry"; the trigger,
  ranking internals, and full cascade have not been stress-tested to the same depth; nothing built/tested on
  real infra yet.
- **8 round-1 red-team fixes** were folded in — but **round 2 found 5 of them do not hold as written** (see below), so treat them as *intended*, not *closed*.

### Round-2 red-team (2026-07-31) — DID NOT converge `[GROUNDED — agent red-team]`
Round 2 (against this spec) came back **harder, not cleaner**: 2 new criticals + 5 fix-as-written failures + a new concurrency front. **This spec is NOT ready for build.** The findings cluster into 3 root themes:

**Theme A — the two-datastore boundary breaks the "atomic" fixes (linchpin = §11 is OPEN).**
"One atomic accept proc" is not well-posed: assignment+status live in FieldJetX, but slot ledger / offers /
idempotency / offer-token live in the **engine DB** — no single transaction spans both until §11 (gate
authority location) is decided and that state is made co-transactional. Same split makes the **cherry-pick
guard TOCTOU** (its offer data isn't in the FJX proc). And `token.subject == T` compares an OIDC subject to a
PersonId with no mapping defined. → **Structural(a) is NOT actually closed.**

**Theme B — never reasoned about at concurrent scale** (~700/day): two emergencies **stack on one tech**
(Rule 7 is only a pool-build filter, not enforced in the gate; emergencies bypass the slot check);
**cross-cascade herding** (N simultaneous cascades all offer the same rank-1 tech → lockstep rejections +
ETA-push storms + transient-empty re-storm); the **familiarity band is an unsound comparator** (intransitive
→ input-order-dependent sort; all-equidistant pools → 0/0 NaN); **gameable ETA** (self-report "free now" to
grab overtime); idle-tech **slotKey ambiguity**; **trigger flap** spawns parallel cascades; **TZ/DST-blind**
dispatch-hours across 46 branches.

**Theme C — zero detection of the one red line:** a P2 bug OR a dispatcher assigning on FJX's native board
creates two owners and **nothing notices** (reconcile checks status, not duplicate owners); System-activity
audit dies when FJX is down.

**2 new criticals:** (1) **No duplicate-owner monitor** → add an independent invariant check alarming on >1
live assignment row per dispatch. (2) **CAS defeated by RFD re-entry** → the State CAS keys only on
status==RFD-GUID; a reprioritize/cancel-reopen/merge restores the same GUID, so a stale non-emergency offer
can commit (emergency store-down → apprentice). Fix: **epoch/cascade-generation token CAS'd alongside status**
+ one-live-cascade-per-dispatch guard.

**5 round-1 fixes that DON'T hold as written:** (i) atomic proc = cross-DB until §11 decided; (ii) cherry-pick
guard TOCTOU/cross-DB; (iii) emergency skill-floor status-contradictory (DECIDED vs out-of-scope vs OPEN) and
**null-unsafe** (`SkillRating>=4` excludes ~3% null-rated techs from EVERY emergency); (iv) "SLA-ordered"
window release contradicts §6.2's "rank by priority label, not the messy SLA clock"; (v) origin coord-integrity
gate polices the wrong data path (`GetNearestVehicles` hides the origin it used).

**Required before this spec can be trusted for build:** (1) decide **§11 gate authority** + make the accept
co-transactional (or saga/outbox + compensating reconcile); (2) design the **concurrency layer**
(cross-cascade coordination, fix the ranking comparator to an absolute epsilon + handle 0/0, gate the ETA,
enforce Rule 7 in the gate, epoch-token CAS); (3) add the **duplicate-owner monitor** + engine-local
operational log + off-hours on-call escalation target; then **re-review (round 3)**. Full output: task `wpy8e3wy0`.

---

## 13. Glossary
- **Dispatch** — a job. **RFD** — Ready-for-Dispatch status (the input queue). **Dispatched** — assigned.
- **Cap-slot** — a unit of a tech's capacity (1 active + 1 upcoming). **Cascade** — staggered sequence of
  offers down the ranked list. **Commit gate** — the single atomic assign operation. **Dispatch Proposal** —
  the job offer to a phone. **ETA Proposal** — the "how long till free?" prompt. **System activity** —
  plain-language narration of engine actions in FJX history. **Follow-Up** — where a revisit goes (not RFD).

---

## 14. Provenance
Drawn from: scope v3.1 §5 (`../_Scope-Doc-v2-2026-07-20/ClimatePros-Stream1-Scope-v3-FINAL.md`); the LOCKED
engine logic (`UC-A-Development-Logic-HANDOFF.md`, `../_UC-A-Requirements-Pack-2026-07-26/UC-A-Dispatch-Engine-LOCKED.md`,
`UC-A-Data-Foundations.md`); the codebase + API hand-off (`UC-A-Build-Context-2026-07-31.md`); the priority
analysis (`UC-A-Priority-Handling-WORKING.md`); the brainstorm log (`UC-A-Engine-Logic-WORKING.md`); the client
transcripts (`../01-Transcripts/`); and read-only staging-DB queries (2026-07-31). Client statements are
`[LOCKED]`; DB/code facts are `[GROUNDED]`; ranking normalization is `[OPEN]`.

_Auto-Dispatch Engine logic spec · techjays · Stream 1 · UC-A · 2026-07-31. Design in progress — see §11–§12._
