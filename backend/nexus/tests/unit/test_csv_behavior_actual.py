"""Actual public synthetic Vitest2.1.9 reports, not StockFlow execution evidence."""

from nexus.builder.csv_behavior_wrapper import qualify_csv_reports
from nexus.builder.csv_report_contracts import CsvCapturedInputs, CsvRegressionPins


def test_actual_pinned_vitest_fractional_timing_reports_qualify_unchanged() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1] / "fixtures/csv-vitest-2.1.9"
    pins = CsvRegressionPins.model_validate_json((root / "pins.json").read_bytes())
    roles = {
        "baseline_shared": "baseline-checks-shared-vitest.json",
        "baseline_web": "baseline-checks-web-vitest.json",
        "before_probe": "post-checks-csv-before-vitest.json",
        "post_shared": "post-checks-shared-vitest.json",
        "post_web": "post-checks-web-vitest.json",
    }
    inputs = CsvCapturedInputs(
        **{
            phase + "_" + kind: (root / (phase + "-" + name)).read_bytes()
            for phase in ("baseline", "post")
            for kind, name in (("module", "index.ts"), ("test", "csv.test.ts"))
        },
        wrapper=(root / "csv-test-wrapper.cjs").read_bytes(),
        **{role: (root / name).read_bytes() for role, name in roles.items()},
    )
    result = qualify_csv_reports(pins, inputs)
    assert (
        len(result.cases) == 7 and sum(row.before_status == "failed" for row in result.cases) == 5
    )
    assert result.reports[0].assertions == 10 and result.reports[1].assertions == 20
