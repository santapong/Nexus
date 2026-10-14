# Native event015 schema gate

Root owns static additive015 and JournalAction(company,id,task) unique target,
plus metadata/FK/NULL/index/RLS/fresh install/downgrade qualification. Checker
owns the accepted Core table extension, unchanged legacy mapper, separate full
NativeBrainEvent mapper and qualified015 projection; exact schema freeze SHA
e85cc91689890aebe34ed9806bcbe9a2be54c64c2444454c1da5b8b47bbf34ce.

Write failing unique-target tests first. Then freeze static migration literals
from the reviewed metadata: seven nullable fields; old six kinds require all
native fields NULL; four new kinds require an exact kind-specific selection and
native SHA while old source/generation fields stay NULL. Scoped FK targets are
RegisteredWork, saved ManagementReportSnapshot, actual DailyBudget and exact
JournalAction action/task. Every full FK prefix has an index. Existing real
resource FK, company forcedRLS and event immutability remain mandatory.

Use only normal independent company Alembic on Root-exclusive
nexus_company_test_native_schema. Fresh/repeat/reflection comparison/downgrade,
restricted SQLNULL/kind/FK/tenant/immutability/index checks qualify schema only.
No native state hashes/body/decision/owner permissions supplied by these
placeholders prove an operational notification; native fact emission is a
separate required package. Handshake015 to checker only after actual schema gate.

Risk: high composite tenant identity and old-column compatibility; mitigate
with unchanged old008/014 direct event SQL (checker2PG3.34s) and014 real ingestion
(1PG3.02s). Full008 ingestion has a pre-existing012 artifact classification read
gap and is explicitly excluded. Downgrade must refuse existing new-kind events
before removing their columns; it cannot silently delete durable evidence.
