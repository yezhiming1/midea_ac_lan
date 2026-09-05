"""Classify pull-request paths into the repository's CI validation lanes."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_DOCUMENTATION_ROOTS = frozenset(
    {
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "README_hans.md",
    },
)
_TOOLING_ROOTS = frozenset(
    {
        ".pre-commit-config.yaml",
        ".prettierignore",
        ".python-version",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "commitlint.config.mjs",
        "mypy.ini",
        "pylintrc",
        "pyproject.toml",
        "release-please-config.json",
        "uv.lock",
    },
)
_ROUTING_PATHS = frozenset(
    {
        ".github/workflows/linter.yml",
        ".github/workflows/validate.yml",
        "scripts/ci_changed_paths.py",
    },
)


@dataclass(frozen=True, slots=True)
class ChangeScope:
    """Summarize which validation contracts a changed-path set affects."""

    documentation: bool
    integration: bool
    vendor: bool
    tooling: bool
    home_assistant: bool
    routing: bool
    unclassified: bool

    @property
    def docs_only(self) -> bool:
        """Whether every changed path is ordinary documentation."""
        return self.documentation and not any(
            (
                self.integration,
                self.vendor,
                self.tooling,
                self.home_assistant,
                self.routing,
                self.unclassified,
            ),
        )

    @property
    def run_functional_tests(self) -> bool:
        """Whether the cross-platform unittest matrix must run."""
        return any(
            (
                self.integration,
                self.vendor,
                self.tooling,
                self.unclassified,
            ),
        )

    @property
    def run_ha_validation(self) -> bool:
        """Whether HACS and hassfest validation must run."""
        return any(
            (
                self.integration,
                self.vendor,
                self.home_assistant,
                self.routing,
                self.unclassified,
            ),
        )

    def as_github_outputs(self) -> Mapping[str, str]:
        """Build stable lowercase values for GitHub Actions outputs.

        Returns:
            GitHub output names mapped to lowercase boolean strings.

        """
        values = {
            "docs_only": self.docs_only,
            "integration": self.integration,
            "vendor": self.vendor,
            "tooling": self.tooling,
            "home_assistant": self.home_assistant,
            "routing": self.routing,
            "unclassified": self.unclassified,
            "run_functional_tests": self.run_functional_tests,
            "run_ha_validation": self.run_ha_validation,
        }
        return {name: str(value).lower() for name, value in values.items()}


def _normalize_path(raw_path: str) -> str:
    candidate = raw_path.strip().replace("\\", "/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    path = PurePosixPath(candidate)
    drive_like_prefix = candidate.partition("/")[0]
    if (
        not candidate
        or candidate.startswith("/")
        or ":" in drive_like_prefix
        or candidate == "."
        or ".." in path.parts
    ):
        msg = f"changed path must be repository-relative: {raw_path!r}"
        raise ValueError(msg)
    return path.as_posix()


def _is_documentation(path: str) -> bool:
    return path in _DOCUMENTATION_ROOTS or path.startswith("doc/")


def _is_vendor(path: str) -> bool:
    return path.startswith("custom_components/midea_ac_lan/_vendor/")


def _is_integration(path: str) -> bool:
    return path.startswith("custom_components/midea_ac_lan/") and not _is_vendor(path)


def _is_home_assistant_metadata(path: str) -> bool:
    return path == "hacs.json" or path.startswith("brands/")


def _is_tooling(path: str) -> bool:
    return path in _TOOLING_ROOTS or path.startswith(
        (".github/", ".vscode/", "scripts/", "tests/"),
    )


def classify_paths(paths: Iterable[str]) -> ChangeScope:
    """Classify changed paths, failing safe for empty or unknown input.

    Returns:
        The aggregate validation scope for all supplied paths.

    """
    flags = {
        "documentation": False,
        "integration": False,
        "vendor": False,
        "tooling": False,
        "home_assistant": False,
        "routing": False,
        "unclassified": False,
    }
    saw_path = False
    for raw_path in paths:
        if not raw_path:
            continue
        saw_path = True
        path = _normalize_path(raw_path)
        if _is_documentation(path):
            flags["documentation"] = True
        elif _is_vendor(path):
            flags["vendor"] = True
        elif _is_integration(path):
            flags["integration"] = True
        elif _is_home_assistant_metadata(path):
            flags["home_assistant"] = True
        elif _is_tooling(path):
            flags["tooling"] = True
        else:
            flags["unclassified"] = True
        if path in _ROUTING_PATHS:
            flags["routing"] = True
    if not saw_path:
        flags["unclassified"] = True
    return ChangeScope(**flags)


def _read_paths() -> list[str]:
    raw = sys.stdin.buffer.read()
    separator = b"\0" if b"\0" in raw else None
    chunks = raw.split(separator) if separator is not None else raw.splitlines()
    return [chunk.decode("utf-8") for chunk in chunks if chunk]


def _write_github_outputs(output_path: Path, outputs: Mapping[str, str]) -> None:
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in outputs.items():
            output.write(f"{name}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the changed-path classifier.

    Returns:
        Zero after outputs are written successfully.

    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    outputs = classify_paths(_read_paths()).as_github_outputs()
    if args.github_output is not None:
        _write_github_outputs(args.github_output, outputs)
    else:
        for name, value in outputs.items():
            sys.stdout.write(f"{name}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
