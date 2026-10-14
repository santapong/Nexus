"""One fresh sealed dispatch, or body-free reconciliation with no provider retry."""

from nexus.execution.notification_worker_context import NotificationContext
from nexus.execution.notification_worker_observation import read_notification_history
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError


async def run_notification_effect(
    services: NotificationDispatchWorkerServices, context: NotificationContext
) -> None:
    """Actual issued native history suppresses a POST regardless of the acquired lease mode."""
    actual = await read_notification_history(services, context)
    if actual.intent_state is not None:
        return
    if context.lease.mode != "execute":
        raise ExecutionDeniedError("Unissued notification reconciliation cannot dispatch")
    await services.dispatcher.dispatch_with_credential(
        context.lease, context.credential, context.draft_id, context.command.action_id
    )
