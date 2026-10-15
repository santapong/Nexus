# Tiny host bootstrap stopped at manager compatibility — 2026-10-15

The first real normal probe stopped in **1.26 seconds**, before starting a
container. Actual typed bus replies reported UID1000 and systemd user-manager
version `262-1`; the frozen native contract accepts only `261.2-1`. Its strict
version validation rejected the current context. This is an unsuccessful probe,
with no containment or offline-cache qualification.

The source was independently reviewed before release: unchanged backend651fd82
plus three private operator modules and two tests (1,581 pinned files).44
pure/mock tests, configured strict typing and both Ruff checks passed. Its finite
profile was60-second scope,15-second container limit and20-second capture budget;
those declared limits are not actual parent-property evidence from this failure.

Only the UID/version queries ran; both subprocesses were recorded complete and
reaped. The inside report has no native parent, sealed container ID, runtime PID,
initial process stamps, snapshots or artifact. Cleanup reported missing sealed ID
and did not kill by name. The failed source, packet, output and terminal logs are
preserved; the original normal namespace will not be retried. Timeout remains held.

Fresh read-only postchecks found the transient unit not loaded, its declared
app-slice cgroup absent, and the proposed container name absent. The existing20
container inventory hash exactly matches the preflight inventory. This supports
the recorded early failure; original native process-retirement evidence was never
captured and is not inferred from those checks.

Evidence under `stockflow/` in the dated implementation evidence directory:

| Artifact | SHA256 |
| --- | --- |
| Frozen source manifest | `70fd6fccc57dccabcc4080f1d8fb392b70d617903a497528df4884759579b903` |
| Original normal packet | `5d138cd74b7354ac86364fb612d6a57b614b32a5fb137f7eb31f16dd192d0e50` |
| Independent source review | `e773e42a1a5ec2f0dbf201f3f2a52a146610c8e2a7837c6909a7743c4e861efa` |
| Actual inside terminal | `947c5419807315efb45bccde15664a801e3e166089457c4498039b19c09fc5b5` |
| Independent failure file audit | `9e7cd68ba133cb9d65a30d562563d7babe4445cfff600c9ef8f4646599529fc2` |

Next is current-manager compatibility research and a fresh bounded raw parent
diagnostic for the typed replies, kernel limits and delegation marker. Updating
the version string alone would not qualify that behavior. The provider identity
includes the supported manager version and contributes to the execution-method
hash, so any extension needs fresh source/profile identity and actual validation.
Historical261.2-1 qualification remains historical; no version value, witness or
authority is fabricated to reuse it on262-1. Source windows and old holds remain.
