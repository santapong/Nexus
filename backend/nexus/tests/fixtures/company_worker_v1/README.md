# Company worker v1 offline fixture

`readiness.json` is synthetic input for `test_company_fake_worker.py`. The predetermined fake model emits a draft; its fake tool records no real effect; its separate fake verifier uses synthetic evidence identifiers. Passing the fixture is not a StockFlow build, provider evaluation, durable-process recovery, or a release.

The fixture binds company/task/trace identities, one logical run, deterministic segment IDs, complete scenario/work/action hashes, workflow/model/tool versions, explicit required counters, exact approval and recorded receipts. Waiting for approval returns immediately; the next segment retains consumed counters. A saved effect intent with no receipt stops as `outcome_unknown`. A saved receipt resumes verification without another model/tool attempt.

Restore requires a trusted expected run and independently persisted minimum counters. A checksum detects accidental corruption; it is not a signature or access control. Production integration still requires authenticated scope, persistent atomic quotas, fenced ownership, single-use approval consumption, transactional enqueue, and actual process-kill/version-upgrade acceptance.
