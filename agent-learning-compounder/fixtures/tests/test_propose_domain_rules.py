"""Tests for P3A: propose_domain_rules mines correction-correlated terms."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSE = REPO_ROOT / "bin" / "propose_domain_rules"


class ProposeDomainRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.tmp.name) / "corpus.txt"
        self.output = Path(self.tmp.name) / "proposals.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_high_score_term_appears_in_proposals(self):
        self.corpus.write_text(
            "[session=s1 outcome=correction] hyperdrive connection timed out hyperdrive\n"
            "[session=s2 outcome=correction] hyperdrive failed hyperdrive\n"
            "[session=s3 outcome=correction] hyperdrive query hung\n"
            "[session=s4 outcome=clean] normal request to api\n"
            "[session=s5 outcome=clean] frontend build green\n"
        )
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "5", "--min-score", "2.0"],
            check=True,
        )
        result = json.loads(self.output.read_text())
        terms = [p["term"] for p in result["proposals"]]
        self.assertIn("hyperdrive", terms)

    def test_drops_stop_words(self):
        self.corpus.write_text(
            "[session=s1 outcome=correction] the the the the the the the the\n"
            "[session=s2 outcome=clean] other content\n"
        )
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "5", "--min-score", "1.0"],
            check=True,
        )
        terms = [p["term"] for p in json.loads(self.output.read_text())["proposals"]]
        self.assertNotIn("the", terms)

    def test_top_k_limits_output(self):
        # All terms are correction-only; all should score the same; top-k caps the count.
        corpus_lines = "\n".join(
            f"[session=s{i} outcome=correction] alpha bravo charlie delta echo foxtrot golf hotel" for i in range(5)
        )
        self.corpus.write_text(corpus_lines + "\n")
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "3", "--min-score", "1.0"],
            check=True,
        )
        terms = [p["term"] for p in json.loads(self.output.read_text())["proposals"]]
        self.assertLessEqual(len(terms), 3)

    def test_empty_corpus_emits_empty_proposals(self):
        self.corpus.write_text("")
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "5", "--min-score", "1.0"],
            check=True,
        )
        result = json.loads(self.output.read_text())
        self.assertEqual(result["proposals"], [])


if __name__ == "__main__":
    unittest.main()
