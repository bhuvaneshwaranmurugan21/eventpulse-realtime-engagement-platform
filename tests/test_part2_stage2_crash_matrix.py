from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "part2/stage2/oracles"))

from part2_stage2_recovery import read_journal, validate_journal  # noqa: E402
from run_part2_stage2_crash_matrix import CRASH_EXIT, supervise  # noqa: E402


class CrashMatrixTests(unittest.TestCase):
    def test_all_eight_process_death_boundaries_converge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"
            summary = supervise(output)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["boundaries_passed"], 8)
            self.assertEqual({row["crash_exit"] for row in summary["results"]}, {CRASH_EXIT})
            for result in summary["results"]:
                case_id = result["case_id"]
                rows = read_journal(output / case_id)
                self.assertEqual(validate_journal(rows), [])
                selected = [row for row in rows if row["boundary"] == case_id]
                self.assertEqual({row["phase"] for row in selected}, {"crash", "restart"})
                self.assertNotEqual(
                    {row["process_id"] for row in selected if row["phase"] == "crash"},
                    {row["process_id"] for row in selected if row["phase"] == "restart"},
                )
                crash_state = json.loads(
                    (output / case_id / "after-crash.json").read_text(encoding="utf-8")
                )
                restart_state = json.loads(
                    (output / case_id / "after-restart.json").read_text(encoding="utf-8")
                )
                self.assertEqual(crash_state["journal_chain_errors"], [])
                self.assertEqual(restart_state["journal_chain_errors"], [])


if __name__ == "__main__":
    unittest.main()
