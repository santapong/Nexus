"""Actual reader configuration and supplied-session delivery; no accepted Engineering fixture."""

from pathlib import Path
from typing import cast

import pytest

from nexus.company.cycle_artifacts.input_reader import CycleInputReader
from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
from nexus.company.cycle_artifacts.publication_contracts import CyclePublicationRules
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.unit.cycle_prerequisite_fixture import configured_reader
from nexus.tests.unit.cycle_publication_row_fixture import cycle_policies
from nexus.tests.unit.strategy_publication_reader_fixture import Policies


def input_reader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CycleInputReader:
    engineering = configured_reader(monkeypatch, tmp_path)
    policies = cast(Policies, engineering.freshness._policies)
    policies.values.update({row.source_symbol: row for row in cycle_policies()})
    return CycleInputReader(engineering, CyclePublicationRules(engineering.catalog, policies))


def original_reader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CycleOriginalReader:
    return CycleOriginalReader(input_reader(monkeypatch, tmp_path))


def described_lease(reader: CycleInputReader, index: int) -> ExecutionLease:
    """Catalog selector only; it is not a claimed row or permission to execute."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    admission = reader.catalog.cycle_admission
    assert admission is not None
    binding = admission.slots[index].child.binding
    return ExecutionLease(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        workflow_version=binding.workflow_version,
        segment_id=uuid4(),
        worker_id=uuid4(),
        fence=1,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        mode="execute",
    )
