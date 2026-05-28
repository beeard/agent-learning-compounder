from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import artifact_envelope


class ArtifactEnvelopeTests(unittest.TestCase):
    def test_analyst_payload_preserves_existing_top_level_shape(self) -> None:
        payload = artifact_envelope.analyst_payload(
            fallback_mode=True,
            fallback_samples_count=2,
            rows=[{"id": "one"}],
        )

        self.assertEqual(set(payload), {"generated_at", "fallback_mode", "fallback_samples_count", "rows"})
        self.assertTrue(payload["fallback_mode"])
        self.assertEqual(payload["fallback_samples_count"], 2)
        self.assertEqual(payload["rows"], [{"id": "one"}])
        self.assertIsInstance(payload["generated_at"], str)

    def test_analyst_payload_rejects_reserved_specific_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved envelope field"):
            artifact_envelope.analyst_payload(
                fallback_mode=False,
                fallback_samples_count=0,
                generated_at="caller-owned",
            )


if __name__ == "__main__":
    unittest.main()
