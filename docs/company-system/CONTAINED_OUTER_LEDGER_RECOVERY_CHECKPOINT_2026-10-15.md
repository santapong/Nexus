# Actual outer-timeout ledger recovery

Checked2026-10-15. One fresh process completed the exact retained orphan-intent
recovery in1.944s, using the original6682148 public APIs and unchanged source bytes.
It invoked only reconciliation-only claim, effect read and one exact lease release.

| Observation | Work fence / segment | Original intent | Reserved cost |
| --- | --- | --- | --- |
| before | running1 /1, original lease expired | intent, fence1, no receipt |0.01USD held, actual unknown |
| claimed | outcome_unknown2 /2, reconciliation lease | outcome_unknown, fence1, no receipt |0.01USD unknown, actual unknown |
| released | outcome_unknown3 /2, no lease | outcome_unknown, fence1, no receipt |0.01USD unknown, actual unknown |

The original action, proposal, registration, intent creation time and one original
attempt remain. Tool use stays1, model/rework/revision use0. The fixed metadata
digest is identical before/after, conserving approvals, daily/work held/spent
totals, source heads, protected artifacts and the other two work rows. A new
reconciliation lease did not renew the original execute lease or any source TTL.

The returned reconciliation lease was still current when released. Root's fresh
SQL confirms the unknown intent at original fence1, work fence3/segment2, no lease,
one attempt and0.01USD/null unknown hold, with zero application backends. The
external monitor was reaped normally; no ambiguous release/retry path was exercised.

No runner, builder invocation, result/receipt, refund, source refresh or engine/proc
inventory/removal occurred. The retained container object remains separate. Unknown
ledger classification is not successful execution or proof of its current engine
state. Sequence CAS plus exclusive fixture use does not provide a general atomic
arbitrary-action preflight guarantee.

Evidence in the private `nexus-contained-outer-ledger-recovery-run-20261015-1`:

- Source freezeee3252ce5475a35c16c8b2ba88597df9770df7eb2bf1eac847210e84da347c52;
  packet1ea0cdaedbb08a15f67474203aa3dce41292b6509001b6674227975f27e4fa3f.
- Source peer1fc9c863752ca3f2c178f6664c436a0f3ef598647cefb543eea6754dc76c693d.
- Root terminal6e25efc6811a04482169108dd08378eb014d1805548255b9c59075315fe43eea.
- Independent file audit20f3a60f005a3ba397991ca8e81e376c39250f82bc72c6f3d9866c045b0b1ae9.

Check-only had verified all1491 original files plus32 helper/input pins. Actual
recovery conserves this named synthetic case; provider billing reconciliation,
object retirement and broader operating recovery remain separate.
