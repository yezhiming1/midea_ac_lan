"""Tests for pull-request path classification."""

# ruff: file-ignore[pytest-unittest-assertion, pytest-unittest-raises-assertion, undocumented-public-method]

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.ci_changed_paths import classify_paths

REPOSITORY_ROOT = Path(__file__).parents[1]


class ChangedPathClassificationTests(unittest.TestCase):
    """Verify positive, negative, mixed, and fail-safe routing examples."""

    def test_plain_documentation_uses_narrow_lane(self) -> None:
        scope = classify_paths(["README.md", "doc/AC.md"])

        self.assertTrue(scope.docs_only)
        self.assertFalse(scope.run_functional_tests)
        self.assertFalse(scope.run_ha_validation)

    def test_integration_source_runs_tests_and_ha_validation(self) -> None:
        scope = classify_paths(["custom_components/midea_ac_lan/climate.py"])

        self.assertTrue(scope.integration)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_vendored_wheel_runs_tests_and_ha_validation(self) -> None:
        scope = classify_paths(
            [
                (
                    "custom_components/midea_ac_lan/_vendor/"
                    "midea_lan-0.0.3-py3-none-any.whl"
                ),
            ],
        )

        self.assertTrue(scope.vendor)
        self.assertFalse(scope.integration)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_python_toolchain_runs_tests_without_ha_validation(self) -> None:
        scope = classify_paths(["pyproject.toml", "uv.lock"])

        self.assertTrue(scope.tooling)
        self.assertTrue(scope.run_functional_tests)
        self.assertFalse(scope.run_ha_validation)

    def test_ha_metadata_runs_only_ha_validation(self) -> None:
        scope = classify_paths(["hacs.json", "brands/logo.png"])

        self.assertTrue(scope.home_assistant)
        self.assertFalse(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_routing_contract_runs_both_validation_lanes(self) -> None:
        scope = classify_paths(["scripts/ci_changed_paths.py"])

        self.assertTrue(scope.tooling)
        self.assertTrue(scope.routing)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_validation_workflow_is_a_routing_contract(self) -> None:
        scope = classify_paths([".github/workflows/validate.yml"])

        self.assertTrue(scope.routing)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_mixed_docs_and_source_do_not_use_narrow_lane(self) -> None:
        scope = classify_paths(
            ["README_hans.md", "custom_components/midea_ac_lan/sensor.py"],
        )

        self.assertFalse(scope.docs_only)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_unknown_path_fails_safe(self) -> None:
        scope = classify_paths(["new_root_contract.txt"])

        self.assertTrue(scope.unclassified)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_empty_input_fails_safe(self) -> None:
        scope = classify_paths([])

        self.assertTrue(scope.unclassified)
        self.assertTrue(scope.run_functional_tests)
        self.assertTrue(scope.run_ha_validation)

    def test_windows_separators_are_normalized(self) -> None:
        scope = classify_paths([r"custom_components\midea_ac_lan\switch.py"])

        self.assertTrue(scope.integration)

    def test_parent_relative_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            classify_paths(["../outside.py"])

    def test_github_outputs_use_lowercase_booleans(self) -> None:
        outputs = classify_paths(["README.md"]).as_github_outputs()

        self.assertEqual("true", outputs["docs_only"])
        self.assertEqual("false", outputs["run_functional_tests"])


class WorkflowRoutingBindingTests(unittest.TestCase):
    """Verify that workflows consume the classifier's routing outputs."""

    def test_linter_binds_docs_and_cross_platform_routes(self) -> None:
        workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "linter.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        lint_block = workflow.split("\n  lint:\n", maxsplit=1)[1].split(
            "\n  tests:\n",
            maxsplit=1,
        )[0]

        self.assertIn("runs-on: ubuntu-latest", lint_block)
        self.assertNotIn("matrix:", lint_block)
        self.assertIn("--from-ref", lint_block)
        self.assertIn(
            "if: needs.changes.outputs.run_functional_tests == 'true'",
            workflow,
        )
        self.assertIn(
            'os: ["windows-latest", "ubuntu-latest", "macos-latest"]',
            workflow,
        )

    def test_ha_validation_binds_relevant_path_route(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "run_ha_validation: ${{ steps.scope.outputs.run_ha_validation }}",
            workflow,
        )
        self.assertIn(
            "if: needs.changes.outputs.run_ha_validation == 'true'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
