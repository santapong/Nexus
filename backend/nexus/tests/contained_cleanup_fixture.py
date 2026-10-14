"""Generated owned container and output bytes; no engine, native permit or DB evidence."""

import json
from uuid import UUID, uuid5

from nexus.builder.contained_cleanup import CleanupIdentity

COMPANY = UUID("00000000-0000-0000-0000-000000000001")
ACTION = UUID("00000000-0000-0000-0000-000000000002")


def identity() -> CleanupIdentity:
    return CleanupIdentity(
        company_id=COMPANY,
        action_id=ACTION,
        container_name="nexus-builder-" + uuid5(COMPANY, str(ACTION)).hex,
        container_id="a" * 64,
        image_id="b" * 64,
    )


def inventory() -> bytes:
    value = identity()
    return (
        json.dumps({"container_id": value.container_id, "container_name": value.container_name})
        + "\n"
    ).encode()


def inspection() -> bytes:
    return json.dumps(identity().model_dump(mode="json") | {"running": False}).encode()
