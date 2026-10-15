# Read-only public-cache reuse checkpoint — 2026-10-16

The fresh manual reuse probe completes with exit 0 in **71.610 seconds**, from
2026-10-15T18:25:40.089447 to 18:26:51.700264 UTC (01:25–01:26 Bangkok).
Its retained receipt reports pnpm 9.12.0, an untouched store, denied store writes
and a successful executable-mode check. Complete stdout and explicit empty stderr
are preserved. Independent actual FILE review is favorable for this scoped reuse.

The input remains the [actual full517 cache](FULL_CAS_PREPARATION_CHECKPOINT_2026-10-16.md):
archive `12f4d370…`, 725,964,800 bytes, and the 26,721-file extracted store.
Complete producer input checks before and after the run take 15.485 and 14.315
seconds and report the same cache, 677,182,266 expanded bytes and 901 tool files.
Their original input/cleanup end is unchanged. Intermediate checks also remain
mandatory in the pinned source. The reviewer verifies retained summaries and
source paths; this review does not independently reread the entire cache or tools.
The earlier preparation audit independently rehashed that archive and every file.

The held source contains 1,634 files: the exact 1,618-file backend at `611cc5e`
plus 16 manual modules. It passes 57 finite checks, configured strict typing and
Ruff check/format for all 16 manual modules. A specialized read-only recipe uses
the existing capture/control/lifecycle and exports one tiny receipt archive.
The 10,240-byte receipt tar is evidence; it never replaces the input cache pin.

The original Source1 review found that successful stderr was omitted. Source2
retains complete separate stdout/stderr with explicit lengths and canonical
base64, including empty streams. Each stream has a fixed 16 KiB bound; overflow
fails instead of truncating a success. Two meaningful parser failures precede the
repair. Source1, its unfavorable review and all original bytes/modes stay preserved.
Source2 has favorable independent forward review and all source files are 0600
inside private 0700 directories.

The new packet freezes a 180-second parent, 90-second payload and 92-second capture,
with 4 GiB/2 CPU/256-PID limits. These bounds were chosen before freeze from measured
full-input validation costs. Dispatch retains the existing original capture end;
it does not renew an admission or execution window. READY precedes PREEXPORT.
CLI wait and final inspect report 0, the final object is stopped without OOM,
the owned runtime is reaped and exact-ID removal succeeds. Initial sealed running
state remains a historical observation alongside the separate stopped outcome.

The independent reviewer reconstructs all 28 fixed query arguments/raw captures,
four consistent parent observations, the exact generated script, receipt framing,
control order and original clocks. Root's separate read-only postcheck finds the
unit not loaded, its cgroup and the three recorded process directories absent,
and the original 21-container inventory unchanged, including retained V4.

Evidence limits are explicit: two strict tree checks succeed in the pinned
producer, but their full tree bodies are not serialized. Only the count, initial
three PID/start/path witnesses, readiness and query/parent metadata remain.
Intermediate input-pass and physical barrier write clocks are also not separately
retained. The audit cannot reconstruct those trees or assert lifetime coverage.

| Evidence | SHA256 |
| --- | --- |
| Source2 hold | `2db674c98054d4d14d4664955ae92b000432e89420c48a2134ca7144e2357fdc` |
| Author check receipt | `9681ad3b9f1025813da919e15c9079d239b2c93e064c7e49b7b634c6b670ac6b` |
| Independent forward source review | `87e54d9247a45eaa77567590662e87c77602e162af2f5693d0b360ea55aaa66e` |
| Root coherent check receipt | `8270e2b43d1812edce67d5b22d97255d08f10ba0e2b2a012941a9a7553666771` |
| Packet | `4e05b746fde41a073518394c90808e526c56629b9985303f806172b78df4e497` |
| Root freeze | `2de17365ef69d5b266f228251e6f8c9aec91fae70974454ac400ff800117a127` |
| Release wrapper | `e1d1bad54e123f63fd0acf46a33f36a275fc51b11392932a0826b01569de79ce` |
| Inner actual terminal | `ee91f4f118aeb1b383e6382eb6198b9a2266c5e4dbb644749962f5a4d7eda55c` |
| Outer actual terminal | `20474f03f469efabad964ee0b00f81d8e401004db778d09a464d020ae25e11cb` |
| Probe receipt tar | `d65eb6c451e9e39ee836a8f5cc8b37691456d45708b265d6ab7b4b91ca683ad6` |
| Receipt body | `6cc50e165a28506f5000e4e3f0d7cbc0979df7608ece0ce117e67535fb122997` |
| Fixed read-only postcheck | `2281dea74737fbbe756c2e065cd9c76c7d3e111a8dd223af9346faa070d0e69a` |
| Independent actual FILE audit | `1637b83af90899c9dafb144e303c9cca3030df6ba5d4c55a51a593b6df81ac27` |
| Actual audit input pins | `719616310b6927b0ae6d8b583507600e774a04253c7ecdc66497d5447e88f3be` |

Data-only real Node-v4 descriptions now adopt the actual cache hash and canonical
paths. They preserve all 914 original preparation files and change only the cache
archive hash and nominated cache symbol. Production configuration validation takes
13.933 seconds. Actual project resolution and Node-v4 timing remain unmeasured.

Next are current-V8 running-fault/recovery checks and fresh real runtime, policy,
candidate and ordered E/EV templates before new Strategy inception. The selected
image-pair [source fix](SELECTED_IMAGE_BINDING_CHECKPOINT_2026-10-16.md) is already
pushed. Current complete V8 stays unconfigured; actual Company E/EV acceptance,
the full readiness cycle and the remaining supervised-release gates stay open.
