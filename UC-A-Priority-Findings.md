# UC-A — Priority: Technical Findings

> For the dev / data team. How the auto-dispatch engine reads and classifies dispatch **urgency**, grounded
> in the **live staging DB** (`FieldJetXStg`, read-only, 2026-07-31). Self-contained. techjays · Stream 1 · UC-A.

## Summary (TL;DR for engineers)
- **Priority is a per-company lookup**, and **colour == the priority value** (one field, not two dimensions).
- **ClimatePros is a single company** (`CompanyId c12d7f16…`, "Climate Pros LLC", ~1.86M of ~1.9M dispatches) → **one priority set, one label→band mapping.**
- **Emergency is not a separate label — it's the `Overtime Approved` (yellow) priority value.**
- A per-dispatch **SLA clock exists** (`SLADate`/`SLATime`, populated) but its time semantics are messy → **Phase 1 ranks by the priority label, not the SLA clock.**
- The engine **consumes the priority as given — it does NOT classify or re-classify urgency** (locked scope rule).

## Data model (verified in `FieldJetXStg`)
- **`dbo.Priority`** — columns: `PriorityId` (uniqueidentifier), `CompanyId` (uniqueidentifier), **`Color`** (int, .NET ARGB), `PriorityName` (nvarchar), `PriorityDesc`, `InsertDt`, `UpdateDt`. **Keyed per `CompanyId`** — each company (FieldJetX is multi-tenant) defines its own priority set + colours.
- **`dbo.PrioritySubTypes`** — PM sub-types (e.g. "PM: Bi-Annual (HVAC)"), FK `PriorityId`.
- **`dbo.Dispatch`** carries: `PriorityId`, `PrioritySubTypeId`, **`SLADate`** (datetime), **`SLATime`** (datetime). ⚠️ **No `PersonId`** on `Dispatch` — the assigned tech lives in a separate **`DispatchAssignments`** row (relevant to the engine's accept path, not to priority).
- **Status GUIDs:** Ready-for-Dispatch = `1248C177-ED7A-4AFE-A0B9-22B304956F37`; Dispatched = `C8F20969-E59B-4375-8060-2472DB095399`.
- **Board/column feed:** `GET DispatchBoard/GetDispatchesByFilter` (search header `dispatchboardsearch`, `statusId` = the column's status GUID).

## ClimatePros priority set — `CompanyId = c12d7f16-e1c9-4689-9f44-89c5ca29afe2`
By real usage across ~1.9M dispatches (colour = `Color` int decoded):

| PriorityName | PriorityId (short) | Color (int) | Colour | Dispatches | Engine band |
|---|---|---|---|---|---|
| Normal | `f76d9d14…` | -16728064 | 🟢 green | 566,695 | **Low / baseline** |
| **Overtime Approved** | `3fe257a3…` | -256 | 🟡 yellow | 532,594 | **Emergency (2–4h)** |
| High | `8df31e86…` | -47872 | 🔴 red | 483,069 | **High (~within a day)** |
| PM | `9b33b03a…` | -16776961 | 🔵 blue | 131,633 | **out of scope (skip)** |
| Hot Parts – ASAP | `82bb9c7e…` | -16711681 | 🩵 teal | 28,928 | ☐ TBD |
| Locked – Scheduled | `dd87160b…` | -16777216 | ⬛ black | 21,426 | ☐ TBD (skip?) |
| Special Equipment | `3225ada7…` | -8689426 | 🟣 purple | 5,248 | ☐ TBD (route/skill?) |
| Warranty (Hot) | `f96b1a29…` | -60269 | 🩷 magenta | 1,768 | ☐ TBD (commercial?) |
| _(null / blank)_ | `00000000…` | — | — | ~89,000 | ☐ **route to dispatcher (fail-safe)** |

## Severity / SLA model (verified + client-confirmed)
- **3-colour severity:** `yellow = emergency (2–4h)` > `red = within a day` > `green = 2+ days`. Confirmed by the client (Michael Magliochetti, discovery Jun-19) *and* the `Color` data.
- **SLA windows are per-customer, contract-driven** (e.g. Target = 2h, Jewel ≈ 4h; penalties for misses).
- `SLADate`/`SLATime` **are populated** and vary by priority (Normal ≈ +1 week; Overtime Approved ≈ same/next-day) — but placeholder-ish values (e.g. `SLATime` 23:59) → **Phase 1 uses the label, not this clock.**
- The **"1–5" scale** referenced elsewhere is **`Person.SkillRating`** (technician skill), **not** an SLA level. (Note: `SkillRating` is ~97% populated → an emergency skill-floor is feasible.)

## Mapping decision (Phase 1)
- **Overtime Approved → Emergency · High → High · Normal → Low · PM / Locked-Scheduled → out of scope.**
- The `PriorityId → band` map is **editable per-company config, not hard-coded** (priority IDs/colours are the client's own settings and can change).
- Engine **reads priority as given; never infers urgency from free-text or SLA.**

## Reproduce (read-only)
```sql
-- priority values + colours for the company:
SELECT PriorityId, Color, PriorityName FROM dbo.Priority
WHERE CompanyId = 'c12d7f16-e1c9-4689-9f44-89c5ca29afe2';
-- usage distribution:
SELECT PriorityId, COUNT(*) n FROM dbo.Dispatch GROUP BY PriorityId ORDER BY n DESC;
-- SLA fields populated?:
SELECT TOP 20 DispatchNumber, PriorityId, SLADate, SLATime, ReceivedDateTime
FROM dbo.Dispatch WHERE ReceivedDateTime < '2026-06-07' ORDER BY ReceivedDateTime DESC;
```

## Open — needs client confirmation
1. Band/handling for the 4 low-volume flags: **Hot Parts, Warranty (Hot), Special Equipment, Locked-Scheduled**.
2. **Null-priority** (~89k) handling — proposed: route to the dispatcher (fail-safe), do not guess a band.
3. Does **yellow stay = emergency**, or is the colour scheme changing (colours are per-company config)?

_techjays · Stream 1 · UC-A · 2026-07-31. Source: staging DB read-only queries + client discovery transcripts._
