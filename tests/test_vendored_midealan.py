"""Integrity checks for the bundled midea-lan runtime wheel."""

# A clean child interpreter is required to prove the test does not accidentally
# use a developer-installed midealan package.
# ruff: file-ignore[suspicious-subprocess-import, pytest-unittest-assertion]

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

COMPONENT_ROOT = Path(__file__).parents[1] / "custom_components" / "midea_ac_lan"
VENDOR_ROOT = COMPONENT_ROOT / "_vendor"
PROVENANCE_PATH = VENDOR_ROOT / "PROVENANCE.json"


class VendoredMideaLanTests(unittest.TestCase):
    """Verify provenance, bytes, and isolated import behavior."""

    def test_wheel_hash_matches_provenance(self) -> None:
        """The bundled wheel must match the reviewed release artifact exactly."""
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        wheel_path = VENDOR_ROOT / provenance["wheel"]

        self.assertTrue(wheel_path.is_file())
        self.assertEqual(
            hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
            provenance["sha256"],
        )

    def test_wheel_imports_in_clean_interpreter(self) -> None:
        """A new interpreter must import the expected version from the wheel."""
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        wheel_path = VENDOR_ROOT / provenance["wheel"]
        script = (
            "import sys; "
            f"sys.path.insert(0, {str(wheel_path)!r}); "
            "import midealan; "
            "from midealan.devices.ac import MideaACDevice; "
            "from midealan.version import __version__; "
            f"assert __version__ == {provenance['version']!r}; "
            "assert '.whl' in midealan.__file__; "
            "assert MideaACDevice is not None"
        )

        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [sys.executable, "-I", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
