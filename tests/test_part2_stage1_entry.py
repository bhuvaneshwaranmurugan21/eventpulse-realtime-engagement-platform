from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import batch, event, record  # noqa: E402

from eventpulse import lambda_entry  # noqa: E402
from eventpulse.local import create_local_runtime  # noqa: E402


class LambdaEntryTests(unittest.TestCase):
    def test_export_uses_lazy_runtime_and_same_handler_factory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = create_local_runtime(Path(directory))
            lambda_entry._handler.cache_clear()
            with patch("eventpulse.aws.create_aws_runtime", return_value=runtime) as factory:
                response = lambda_entry.lambda_handler(
                    batch(record(event("entry-event", 1_000), "1")), None
                )
                again = lambda_entry.lambda_handler(
                    batch(record(event("entry-event", 1_000), "2")), None
                )
            self.assertEqual(response, {"batchItemFailures": []})
            self.assertEqual(again, {"batchItemFailures": []})
            factory.assert_called_once_with()
            self.assertEqual(len(runtime.store.export()["identity_ledger"]), 1)
            lambda_entry._handler.cache_clear()


if __name__ == "__main__":
    unittest.main()
