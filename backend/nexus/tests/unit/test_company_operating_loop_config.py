"""Only fixed reloadable server registration selects one already saved native occurrence."""

from pathlib import Path
from uuid import uuid4

import pytest

from nexus.company.management.native_loop_config import (
    load_native_operating_registration,
    save_native_operating_registration,
)
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.tests.unit.test_company_native_profile_contracts import profile


@pytest.mark.parametrize("field", ["owner_identity", "approved", "tool", "new_goal", "endpoint"])
def test_registration_cannot_supply_identity_approval_work_or_endpoint(field: str) -> None:
    reference = profile()
    values = {
        "company_id": reference.company_id,
        "registration_id": uuid4(),
        "profile": reference,
        field: True,
    }
    with pytest.raises(ValueError):
        NativeOperatingRegistration.model_validate(values)


async def test_fixed_registration_reload_and_exact_save_replay(tmp_path: Path) -> None:
    reference = profile()
    registered = NativeOperatingRegistration(
        company_id=reference.company_id, registration_id=uuid4(), profile=reference
    )
    path = tmp_path / "registered.json"
    await save_native_operating_registration(path, registered)
    before = path.read_bytes()
    await save_native_operating_registration(path, registered)
    assert path.read_bytes() == before
    assert await load_native_operating_registration(path) == registered
    changed = registered.model_copy(
        update={"profile": reference.model_copy(update={"report_id": uuid4()})}
    )
    with pytest.raises(ValueError, match="immutable"):
        await save_native_operating_registration(path, changed)
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "oversized", "extra", "foreign"])
async def test_untrusted_config_is_bounded_and_not_a_registration_permit(
    tmp_path: Path, kind: str
) -> None:
    reference = profile()
    registration = NativeOperatingRegistration(
        company_id=reference.company_id, registration_id=uuid4(), profile=reference
    )
    path = tmp_path / "registered.json"
    if kind == "symlink":
        target = tmp_path / "elsewhere.json"
        target.write_text(registration.model_dump_json())
        path.symlink_to(target)
    elif kind == "oversized":
        path.write_bytes(b"x" * 65537)
    elif kind == "extra":
        path.write_text(registration.model_dump_json()[:-1] + ',"approved":true}')
    else:
        path.write_text(registration.model_copy(update={"company_id": uuid4()}).model_dump_json())
    with pytest.raises(ValueError):
        await load_native_operating_registration(path)
