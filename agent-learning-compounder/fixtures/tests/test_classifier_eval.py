import json
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_classifier.py"
FIXTURES = ROOT / "fixtures" / "eval-fixtures" / "classifier_precision.json"


class ClassifierEvalTests(unittest.TestCase):
    def test_classifier_precision_and_recall_meet_threshold(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixtures",
                str(FIXTURES),
                "--min-precision",
                "0.85",
                "--min-recall",
                "0.85",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(payload["precision"], 0.85)
        self.assertGreaterEqual(payload["recall"], 0.85)
        self.assertTrue(payload["passed"])
        self.assertIn("false_positive_domains", payload)
        self.assertIn("false_negative_domains", payload)


if __name__ == "__main__":
    unittest.main()
