"""Constant independent-publication denial without raw/foreign record reflection."""

from nexus.execution.runtime_contracts import ExecutionDeniedError


class AcceptanceDeniedError(ExecutionDeniedError):
    """Protected actual evidence/current publication authority is unavailable."""


def require_acceptance(condition: bool) -> None:
    if not condition:
        raise AcceptanceDeniedError("Current independent acceptance target is unavailable")
