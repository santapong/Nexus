"""Actual native watch plus fresh original source-window producer for one issued job."""

from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.native_state import current_source
from nexus.builder.runner_capture import LeaseWatch


class ContainedSourceWatch:
    """Server-only composition; this adapter grants no new permit or current-member authority."""

    def __init__(self, native: LeaseWatch, *, operation_end_us: int) -> None:
        if type(operation_end_us) is not int or operation_end_us <= 0:
            raise ValueError("Contained watch requires a fixed original operation end")
        self.native, self.operation_end_us = native, operation_end_us

    async def before_spawn(self) -> SpawnWindow:
        """Renew through the existing watch, then obtain current native final-clock evidence."""
        await self.native.check()
        window = await current_source(
            self.native.factory,
            self.native.guard.lease,
            self.native.identity,
            self.native.action,
            self.native.guard,
            issued=True,
            operation_end_us=self.operation_end_us,
        )
        if window is None:
            raise ValueError("Contained watch current source window is unavailable")
        return window

    async def check(self) -> None:
        """Preserve existing source/lease checks throughout process observation."""
        await self.native.check()
