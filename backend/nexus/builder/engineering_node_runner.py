"""Explicit diamond composition preserves Node execution and engineering witness/recovery."""

from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.node_runner import NodeNativeBuilderRunner


class EngineeringNodeBuilderRunner(EngineeringNativeBuilderRunner, NodeNativeBuilderRunner):
    """Engineering prepare/reconcile delegate through Node runtime to one generic native runner."""
