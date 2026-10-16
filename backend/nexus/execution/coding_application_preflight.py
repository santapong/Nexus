"""Full coding normal017/restricted/durable boot only; no actor/work/key readiness prerequisite."""

from nexus.company.management.planning_native_facts import require_time
from nexus.execution.coding_application import CodingApplication
from nexus.execution.planning_application import require_planning_http_signer
from nexus.execution.qualification_application import preflight_qualification_database


async def preflight_coding_database(value: CodingApplication, *, end_us: int) -> None:
    """Normal017 is installed separately; boot creates no migration or new authority."""
    require_time(end_us)
    value.require_composition()
    require_planning_http_signer(value.planning)
    await preflight_qualification_database(
        value.services.factory, end_us=end_us, schema_versions=("company_017",)
    )
    require_time(end_us)
    value.require_composition()
    require_planning_http_signer(value.planning)
