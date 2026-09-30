from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_part2_stage3_mutations import run  # noqa: E402


class Stage3MutationTests(unittest.TestCase):
    def test_all_mandatory_semantic_mutants_are_killed(self) -> None:
        self.assertEqual(run()["mutants_killed"], 12)


if __name__ == "__main__":
    unittest.main()
