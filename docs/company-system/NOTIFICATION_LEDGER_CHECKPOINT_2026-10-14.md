# Notification ledger checkpoint

Normal014 installs four append-only company-scoped histories: immutable drafts,
native event coalescing links, permanent exact M1 dispatch bindings and safe
provider observations. Complete event sequence and intent task/trace/run/fence/
kind/proposal hashes are native FK targets. The dispatch FK is deferred until
commit, allowing the trusted before-intent hook and actual M1 intent to share one
transaction. No row can substitute a different trace, fence, proposal or model
attempt. One uncertain intent never authorizes another send.

Tenant RLS, immutability, SQL NULL branches, UTF8 limits, actual Bangkok issuance
day, native memberships and full covering FK/query indexes are installed. A
provider submission/response ID describes acceptance only. Delivery must match
the actual provider event; sent/opened/clicked does not imply delivered. Initial
submission uniqueness is permanent; later observations append without rewriting
the earlier result. Billing remains the M1 ledger's separate concern.

## Actual source and qualification

Base9ceecbc plus36Python overlays is captured in
`/mnt/data/nexus-implementation-evidence-2026-10-14/notification014-checkpoint-source.json`.
New native store/recipient/operating loop/builder working files are excluded.
Whole1219unit15.72s/19existing warnings and strict/Ruff/format36 pass. The pure
notification freeze77checks1.13s and model freeze6metadata0.63s retain their original
scope and hashes; importing/compiling declarations was not described as DB proof.

Actual restricted PostgreSQL qualification is19cases: fresh/repeat/metadata/
downgrade1PG2.32s; tenant/immutability/index/draft NULL/native event sequence6PG16.96s;
real M1 before-intent binding+intent commit/replay and mismatched tuple rollback
5PG21.15s; provider NULL/acceptance-versus-delivery/initial uniqueness7PG29.90s.
The tests use actual native plans/actions/leases/intents but placeholder draft
JSON solely to exercise SQL. They send no email and are not native notification
publication or business evidence. Root schema DB normal teardown is verified.

## Required next gates

The native notification store/actual event loader and mandatory registered current
owner recipient source now may use qualified014 on its exclusive notifications
DB. Recipient/source/publication/final clock/daily cap and actual one-permit
transport integration still need proof. Required decisions, blockers, caps and
registered digests lack old Brain wakes; additive015 must install actual native
event references/emitters with old-profile compatibility. Existing six event
kinds and columns are preserved in014. Full NOTIFY-01 is not satisfied by this
ledger. Sender/domain/recipient/live provider acceptance and delivery, owner UI,
private deployment/recovery and supervised release approval remain required.
No schedule, worker, email, provider, Pi or deployment is activated here.
