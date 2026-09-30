from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_part2_stage3_properties import run  # noqa: E402


class Stage3PropertyTests(unittest.TestCase):
    def test_frozen_generated_and_metamorphic_properties(self) -> None:
        self.assertEqual(run()["total_generated_checks"], 208)


if __name__ == "__main__":
    unittest.main()
