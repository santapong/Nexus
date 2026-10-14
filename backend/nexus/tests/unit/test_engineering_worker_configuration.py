"""Failed DBOS construction must not poison trusted worker configuration; no runtime launches."""

from typing import cast

import pytest

from nexus.execution.engineering_worker_services import EngineeringWorkerServices


def test_failed_runtime_constructor_leaves_worker_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    import nexus.execution.engineering_worker as worker

    monkeypatch.setattr(worker, "_services", None)

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Synthetic DBOS initialization unavailable")

    monkeypatch.setattr(worker, "DBOS", unavailable)
    # Only constructor behavior is exercised; no service method or effect is called.
    services = cast(EngineeringWorkerServices, object())
    with pytest.raises(RuntimeError, match="initialization unavailable"):
        worker.configure_engineering_worker(services, "postgresql://fixture")
    assert worker._services is None
    monkeypatch.setattr(worker, "DBOS", DBOS)
