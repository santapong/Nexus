# Complete engineering bodies — actual restricted SQL

Checked2026-10-15. A fresh five-case recipe passes **28.18 seconds**; the Root
wrapper completes28.984s with no application sessions remaining. Backend basis
is `29bfdc6` plus six private test fixtures, not a changed production reader.
This closes the bounded reader SQL prerequisite; real E/EV jobs remain open.

Five distinct companies used public directory membership/work registration,
ingestion and READ grants. The reader used a real registered member/task scope,
the restricted NOSUPER/NOBYPASS application role, forced RLS and normal001–015
migrations. No execution lease, action, intent, receipt or acceptance was fabricated.

Proven cases:

- Complete65,536-byte UTF-8 body: exact full/span hashes, five returned pages,
  three native UTF-8 boundary retreats, eight blob reads/524,288 actual I/O bytes,
  and460 application SQL statements. The genuine first slice retains has_more.
  The local read took1.5391s; a public16,385-byte request was denied.
- Actual public READ revocation after the first successful page denied the next
  native request at offset16,381. No complete body was returned.
- The original eight-second grant expired after the first page; the actual next
  page denied. The same original grant also appears in the first protection data.
- A separate original eight-second grant remained live through the actual native
  full-reference revalidation, then expired during a forwarding observer's wait.
  The unchanged final production window check denied without returning a body.
- In the exclusive fixture DB, one explicitly released admin fault changed only
  ASCII byte65,535, preserving the original ref/blob/prefix/length. The immutable
  trigger was disabled and reenabled atomically for that single update. Actual
  restricted app UPDATE attempts raised P0001 before and after. The native prefix
  check passed, while the paired full-reference check rejected the changed tail.

Original expiry clocks, UTC:

| Case | Before | Original expiry | After |
|---|---|---|---|
| Next page |08:51:25.867004|08:51:33.247606|08:51:33.319100|
| Final check |08:51:36.113833|08:51:42.550381|08:51:42.602419|

No source/grant/credential window was renewed. Helper30s, SQL statement2s and
whole-recipe290s/OS300s bounds remain unchanged. This measures one synthetic64KiB
body; it does not establish maximum512KiB collection or StockFlow pair timing.

Root terminal SQL confirms015, five companies/registered works/artifacts,
four unchanged stored hashes plus the planned changed tail, triggerO, forced RLS
and0application sessions. Execution work, attempts, intents, actions, holds and
work-budget rows are all0. Five original protected blobs and both databases/runs
remain preserved; the labelled corrupt row is not silently repaired.

Evidence:

- Source `/home/santapong/.codex/nexus-engineering-bodies-sql-v2-20261015-1`;
  full1582-file manifest `e9eb672246c9e3289caff47769c0fbe1b84d6a3ee9eeaa8efdeeb626c0df1200`.
- Freeze `c286b169e7185d91ad2e7d7fb8c07ceca7f0836a64ffb874684781821beb047a`;
  packet `760d50bbd4d4d5c93b3c8dbe2286d6bf49daab29c3f8548d1d2e0d97d89c165f`.
- Root release `8f5b2f8722834be1d2440a69ddf739eb7d5ac96ebdc6b893686e3f72a0efa4ca`.
- Root terminal `0413a067ff6d58bd255c4a3f7c675c312a1a11a1fdabe0047105215a6c1e81b3`
  pins11 prior run files; terminal file audit
  `89090fee121ede450d8219717c29ea2ef297eb161a9094d425914d09112146e0`
  independently verifies spans, clocks, tail, ledgers and cleanup.

First source1 failed31.80s before tail mutation: asyncpg returned PostgreSQL's
internal catalog char as bytes, but the fixture expected text. Root's read-only
probe `6f4b1d5ccc48cbab39457bf4dbab42217dee201a1253da81aa2b6272796e2d79`
proved bytes4f versus explicit textO. Fresh v2 changed only two SQL::text
projections and closed fixture identities; all predicates/windows stayed intact.
See ERROR128. Original failed terminal `1eee7cdd9df5130764046b928bf813d4d17162490cfd0981cbe5cc9f22342502`
and its four completed cases remain preserved.

Next: verified runtime dependency restoration, real StockFlow Node-v4 timing,
genuine selected E/EV jobs and independent engineering acceptance. No Node,
provider, SDK worker, email, ARM64, deployment or full-release proof follows here.
