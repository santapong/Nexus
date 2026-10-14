# Native cancellation and artifact provenance checkpoint

Checked 2026-10-14 on `feature/company-foundation`, after core commit `7eaf9db`.
This is a local offline implementation checkpoint. M3 completion, live model quality,
company-operation completion and release deployment remain unclaimed.

## Delivered boundaries

- Owner cancellation records immutable exact native work/run/actor intent. Descendants
  inherit the stop. A stopped procedure cannot restart by substituting new plan/root/child
  IDs for the same goal. Fresh claims, dispatch, execution attempts and lease renewals
  deny the stop. Already issued receipts, reconciliation, charges and counters remain.
- Normal additive company011 installs the cancellation history. Company012 installs
  native artifact-input/resource-input edges and optional persisted generated artifact
  classification, with company UUID foreign keys, forced RLS and immutable history.
  Earlier migrations are unchanged.
- Artifact reads, source eligibility before ranking, reference qualification and contributor
  closure include every parent artifact resource, private source and explicit resource edge.
  Stronger input classification propagates. Missing origin leaves and cycles deny access.
  Supported origins are existing actual source/derivation records; source-free origin
  qualification is not implemented.
- Owner-provisioned artifact targets explicitly grant readership. Replaying provisioning
  cannot reactivate a revoked grant. Provisioning grants no action/write/spend authority.
- Mechanical report inputs distinguish a registered source policy with no expiry from
  unknown freshness. A deterministic renderer quotes exact UTF8 bytes and preserves
  actual date precision, native accepted-work identities and unknown billing.

## Evidence and scope

Evidence lives under `/mnt/data/nexus-implementation-evidence-2026-10-14/`.

| Boundary | Evidence |
| --- | --- |
| Cancellation and pre011 compatibility | Author freeze47 checks:36 restricted PostgreSQL and11 unit,64.20s; strict/lint/format19 files |
| Normal012 schema | Fresh/repeat/metadata/downgrade1 PostgreSQL test,1.91s;69 company-profile tables |
| Artifact permissions and target readership | Root10 PostgreSQL cases,37.81s, `artifact-input-retained.log` |
| Independent ancestry review | Six unchanged ACL/classification/head/missing-origin probes,35.19s; `artifact-review/review-verdict-fixed.json` |
| Existing Brain retrieval/reference regression |17 PostgreSQL cases,103.84s; `artifact-post-review-brain-regression2.log` |
| Registered no-expiry/checker boundary |91 unit checks,1.13s; actual no-expiry/policy mismatch2 PostgreSQL cases,12.78s |
| Pure exact renderer |6 unit checks,1.83s |
| Exact staged source checkpoint |1,033 unit checks,32.11s,19 existing warnings; strict/lint/format43 source files;32 CI matrix paths validated locally |

The independent review first reproduced ancestry privacy and missing-origin defects;
original failing observations are retained. Its final verdict is scoped to corrected012
read/provenance boundaries, not to the in-progress generated artifact publisher.
Source manifests bind exact file hashes; tests using seeded artifact metadata explicitly
prove schema/read conformance, not approved business execution.
The isolated tested source tree is `f382abe46f5af4753458e4d72419b34d96129c1a`;
subsequent documentation records this result without changing those source bytes.
Remote CI execution is not claimed. The separate evolving checkout also passed1,069
unit checks,28.28s, but includes active packages excluded from this checkpoint.

## Work continuing

Native saved-report capture, full generated report/check publication, actual DBOS procedure
execution, scheduler cancellation projection, commitments and the owner HTTP/UI are being
integrated separately. Root native report preparation/check preparation currently has2
PostgreSQL cases passing32.52s; scheduler cancellation plus existing scheduling has8
passing58.28s. These active files are outside this commit's frozen provenance boundary.

After the native procedure passes a coherent failure/recovery and permissions review,
the release still needs ARM64 builder qualification, actual owner session/browser proof,
configured provider/email qualification, StockFlow readiness execution, private access,
backup/restore and the applicable final deployment/publication decision. The earlier
offline Brain scorer is retained unchanged and is not customer-readiness evidence.
