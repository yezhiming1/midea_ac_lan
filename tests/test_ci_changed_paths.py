"""Tests for pull-request path classification."""

# ruff: file-ignore[pytest-unittest-assertion, pytest-unittest-raises-assertion, suspicious-subprocess-import, subprocess-without-shell-equals-true, undocumented-public-method]

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.ci_changed_paths import classify_paths

REPOSITORY_ROOT = Path(__file__).parents[1]
GIT_EXECUTABLE = shutil.which("git")


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git against a disposable test repository.

    Returns:
        The completed Git process.

    Raises:
        RuntimeError: If Git is unavailable.

    """
    if GIT_EXECUTABLE is None:
        raise RuntimeError("Git is required for CI routing contract tests")
    return subprocess.run(
        [GIT_EXECUTABLE, *arguments],
        cwd=repository,
        check=check,
        capture_output=True,
    )


def _initialize_repository(repository: Path) -> None:
    """Create a deterministic disposable Git repository."""
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "CI routing tests")
    _git(repository, "config", "user.email", "ci-routing@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")


def _commit(repository: Path, message: str) -> str:
    """Commit every fixture change and return the commit identity.

    Returns:
        The new commit SHA.

    """
    _git(repository, "add", "--all")
    _git(repository, "commit", "--message", message)
    return _git(repository, "rev-parse", "HEAD").stdout.decode().strip()


def _classify_git_diff(diff_output: bytes) -> dict[str, str]:
    """Pass raw NUL-delimited Git output through the real classifier CLI.

    Returns:
        The classifier's GitHub-style outputs.

    """
    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "ci_changed_paths.py"),
        ],
        input=diff_output,
        check=True,
        capture_output=True,
    )
    return dict(
        line.split("=", maxsplit=1) for line in result.stdout.decode().splitlines()
    )


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


class GitDiffRoutingIntegrationTests(unittest.TestCase):
    """Exercise Git history and rename output through the classifier CLI."""

    def test_docs_only_diff_requires_base_history_in_lint_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            _initialize_repository(source)
            (source / "README.md").write_text("base\n", encoding="utf-8")
            base_sha = _commit(source, "docs: add base readme")
            _git(source, "switch", "--create", "feature")
            (source / "README.md").write_text("head\n", encoding="utf-8")
            head_sha = _commit(source, "docs: update readme")

            checkout = root / "checkout"
            _git(
                root,
                "clone",
                "--depth",
                "1",
                "--branch",
                "feature",
                source.as_uri(),
                str(checkout),
            )
            shallow_diff = _git(
                checkout,
                "diff",
                "--name-only",
                "-z",
                "--diff-filter=ACMRTD",
                base_sha,
                head_sha,
                check=False,
            )
            self.assertNotEqual(0, shallow_diff.returncode)

            _git(checkout, "fetch", "--unshallow", "origin")
            complete_diff = _git(
                checkout,
                "diff",
                "--name-only",
                "-z",
                "--diff-filter=ACMRTD",
                base_sha,
                head_sha,
            )
            self.assertEqual(b"README.md\0", complete_diff.stdout)
            self.assertEqual(
                "true",
                _classify_git_diff(complete_diff.stdout)["docs_only"],
            )

    def test_source_rename_into_docs_keeps_broad_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            _initialize_repository(repository)
            source = repository / "custom_components" / "midea_ac_lan"
            source.mkdir(parents=True)
            old_path = source / "routing_example.py"
            old_path.write_text("ROUTING_EXAMPLE = True\n", encoding="utf-8")
            base_sha = _commit(repository, "test: add integration source")

            destination = repository / "doc" / "routing_example.md"
            destination.parent.mkdir()
            _git(
                repository,
                "mv",
                old_path.relative_to(repository).as_posix(),
                destination.relative_to(repository).as_posix(),
            )
            head_sha = _commit(repository, "docs: move source into documentation")

            default_diff = _git(
                repository,
                "diff",
                "--name-only",
                "-z",
                "--diff-filter=ACMRTD",
                base_sha,
                head_sha,
            )
            self.assertEqual(b"doc/routing_example.md\0", default_diff.stdout)
            self.assertEqual(
                "true",
                _classify_git_diff(default_diff.stdout)["docs_only"],
            )

            safe_diff = _git(
                repository,
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                "--diff-filter=ACMRTD",
                base_sha,
                head_sha,
            )
            self.assertEqual(
                {
                    "custom_components/midea_ac_lan/routing_example.py",
                    "doc/routing_example.md",
                },
                set(safe_diff.stdout.decode().strip("\0").split("\0")),
            )
            outputs = _classify_git_diff(safe_diff.stdout)
            self.assertEqual("false", outputs["docs_only"])
            self.assertEqual("true", outputs["run_functional_tests"])
            self.assertEqual("true", outputs["run_ha_validation"])


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
        self.assertIn("fetch-depth: 0", lint_block)
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

    def test_workflows_disable_rename_detection_for_path_classification(self) -> None:
        for workflow_name in ("linter.yml", "validate.yml"):
            workflow = (
                REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
            ).read_text(encoding="utf-8")

            self.assertIn("git diff --no-renames --name-only", workflow)


if __name__ == "__main__":
    unittest.main()
