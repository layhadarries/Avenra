# Stage 10 reliability verification (engineering complete)

Baseline: `7b3b380` (dashboard-matched private PWA), following `stage-9-complete`.
This is local fictional-data engineering work. No live worker/provider, scheduler,
notification, invitation, database migration or deployment is involved.

## Failure policy

- A server receipt means durable application storage, not delivery or human help.
  The PWA distinguishes saved-on-phone, server received and responder acknowledgement.
- Provider acceptance is not delivery; a contact acknowledgement does not change
  responder/workflow state. Missing/ambiguous provider responses stay unknown.
- Outbox claims commit before transport. A crash after claim or after provider
  acceptance but before audit/DB commit cannot be safely retried: recovery marks
  uncertainty, never puts that claim back in pending. No automatic channel fallback.
- Ownership/subscription checks happen again before transport. Revocation cannot
  recall a notification already handed to a provider. There is no distributed
  transaction or exactly-once guarantee across the database/provider boundary.

## Bounded recovery change

Each recovery call inspects at most 100 processing claims and marks at most 100
unknown. Missing, malformed or timezone-naive claim times are unknown, not proof
of a completed/failed send. A durable, transaction-owned rotating cursor in
`app_metadata` ensures recent claims at the front cannot permanently starve
later claims; the scan wraps when it reaches the end. The cursor is bookkeeping,
not a job deletion or authority grant. Values remain bound parameters.

Parsing aware timestamps in the repository avoids PostgreSQL aborting a recovery
transaction while casting corrupt TEXT. It retains UTC comparisons without a
new schema migration. At a large backlog, multiple scheduler ticks are needed;
the 900-second stale threshold is not a guaranteed recovery SLA. Future/invalid
clock behaviour and backlog/heartbeat require operational monitoring.

## Evidence

Failing-first tests reproduced missing/malformed claim starvation and unbounded
recovery. `tests/test_stage10_reliability.py` now passes **13 checks** covering:

- single alert/outbox set under concurrent same-client capture;
- SMS and Web Push single-job contention with one fake send;
- reconnect after a committed claim, no retry of uncertainty;
- accepted fake send followed by audit failure and recovery to unknown;
- missing/malformed timestamps, bounded batches and rotating-cursor progress;
- contact owner changes, subscription corruption and revocation after decrypt;
- no secret-bearing audit details or claims of delivery from provider acceptance.
- PostgreSQL-translated recovery uses typed, bound parameters; malformed claim
  times are parsed without a failing SQL timestamp cast.

All **34 existing notification tests** pass. Existing Stage 2 HELP and Stage 5
diary Chromium tests and all **34 Node checks** passed after the private UI update.
Final full backend regression passed **474 tests in 708.333 seconds**. Existing
fixture resource-cleanup warnings remain. The earlier 473-test pass preceded the
last PostgreSQL typing regression; a server restart interrupted the first final
rerun, and the fresh 474-test pass establishes the final result. Web Push (32),
hosted-worker (7) and ownership/offline Chromium checks also passed. Dependency
consistency and diff/credential-pattern review pass. `stage-10-complete` records
local engineering verification, not deployment approval. SQLite concurrency/fake transport are
not live PostgreSQL load, physical phones, provider acceptance or operational SLA
evidence. Stages 11–12 and the hosted rollout remain separate work.
