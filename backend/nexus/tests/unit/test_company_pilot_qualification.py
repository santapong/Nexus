"""CLI selection remains explicit, local and separate from migrations/credentials."""

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from nexus.execution.qualification_application import (
    company_database_url,
    require_admin_database,
)
from nexus.settings import Settings


def test_generic_database_has_no_legacy_fallback_and_admin_must_match_target() -> None:
    with pytest.raises(ValueError):
        company_database_url(Settings(_env_file=None, company_database_url=""))
    app = "postgresql+asyncpg://nexus_company_app@/company_application?host=/tmp/mock&port=55438"
    settings = Settings(_env_file=None, company_database_url=app)
    assert company_database_url(settings) == make_url(app)
    assert (
        require_admin_database(
            app.replace("+asyncpg", "+psycopg").replace("nexus_company_app@", "operator@"),
            make_url(app),
        ).username
        == "operator"
    )
    for wrong in (
        app.replace("+asyncpg", "+psycopg"),
        app.replace("company_application", "foreign").replace("nexus_company_app@", "operator@"),
    ):
        with pytest.raises(ValueError):
            require_admin_database(wrong, make_url(app))


def test_default_pilot_serve_and_generic_modes_are_explicit_in_actual_parser() -> None:
    import ast

    script = Path(__file__).resolve().parents[3] / "scripts/company_pilot.py"
    tree = ast.parse(script.read_text())
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {
        "qualification-api",
        "qualification-worker",
        "qualification-migrate",
        "--qualification-config",
        "--qualification-config-sha",
        "--worker-credential-fd",
        "--admin-database-fd",
    } <= literals
    # Code must keep operator mode dispatch before disposable config_at (signer/account root).
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    operator = next(
        node
        for node in main.body
        if isinstance(node, ast.If) and "qualification-api" in ast.unparse(node.test)
    )
    config = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign) and ast.unparse(node.value).startswith("config_at(")
    )
    assert main.body.index(operator) < main.body.index(config)


@pytest.mark.parametrize(
    "mode,extra",
    [
        ("qualification-api", []),
        ("qualification-worker", ["--worker-credential-fd", "8"]),
        ("qualification-migrate", ["--admin-database-fd", "9"]),
    ],
)
def test_actual_cli_parser_never_loads_disposable_signer_or_account_for_generic_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    extra: list[str],
) -> None:
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[3] / "scripts/company_pilot.py"
    spec = importlib.util.spec_from_file_location("nexus_qualification_cli_unit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module, "qualification_mode", lambda args: calls.append(args.mode))
    monkeypatch.setattr(
        module,
        "config_at",
        lambda root: (_ for _ in ()).throw(AssertionError("No disposable identity load")),
    )
    args = [
        str(script),
        mode,
        "--qualification-config",
        "/unused/config.json",
        "--qualification-config-sha",
        "a" * 64,
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", args)
    module.main()
    assert calls == [mode]
    monkeypatch.setattr(sys, "argv", [*args, "--root", "/unused/pilot-root"])
    with pytest.raises(SystemExit):
        module.main()
    assert calls == [mode]
