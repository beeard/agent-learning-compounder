"""Tests for P3A: propose_domain_rules mines correction-correlated terms."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSE = REPO_ROOT / "bin" / "propose_domain_rules"
REFRESH = REPO_ROOT / "bin" / "refresh_learning_state"


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

    def test_accepts_extract_sessions_format(self):
        """Lines from `extract_sessions` (`role: text [session_ref=...]`) should
        be parsed via the fallback; sessions containing correction-pattern
        words in user turns are tagged correction, others clean."""
        self.corpus.write_text(
            "user: please fix the hyperdrive timeout, instead try the new client. [session_ref=s1]\n"
            "assistant: ok, switching to the new client. [session_ref=s1]\n"
            "user: thanks, that worked. [session_ref=s1]\n"
            "user: just run the build please. [session_ref=s2]\n"
            "assistant: build green. [session_ref=s2]\n"
        )
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "10", "--min-score", "0.5"],
            check=True,
        )
        terms = [p["term"] for p in json.loads(self.output.read_text())["proposals"]]
        # 'hyperdrive' came from the correction session, 'build' from the clean one.
        # The proposer should surface 'hyperdrive' (correction-correlated).
        self.assertIn("hyperdrive", terms)


class RefreshWiresDomainRuleProposer(unittest.TestCase):
    """refresh_learning_state should append domain_rule_candidate rows when given a corpus."""

    def test_refresh_queues_domain_rule_candidates(self):
        fixture_src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        seed = fixture_src / "seed"

        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import state_paths  # type: ignore

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            shutil.copytree(fixture_src, repo, ignore=shutil.ignore_patterns("seed"))

            rid = state_paths.repo_id(repo)
            state_root = repo / ".agent-learning"
            state_dir = state_root / "repos" / rid
            state_dir.mkdir(parents=True, exist_ok=True)
            for name in (
                "config.json",
                "baseline.json",
                "domain-rules.active.json",
                "skill-map.json",
            ):
                shutil.copy(seed / name, state_dir / name)
            shutil.copy(seed / "config.json", state_root / "config.json")

            # Seed a small corpus with correction-correlated terms.
            corpus = Path(td) / "corpus.txt"
            corpus.write_text(
                "[session=s1 outcome=correction] hyperdrive connection timed out hyperdrive\n"
                "[session=s2 outcome=correction] hyperdrive failed hyperdrive\n"
                "[session=s3 outcome=correction] hyperdrive query hung\n"
                "[session=s4 outcome=clean] normal request to api\n"
                "[session=s5 outcome=clean] frontend build green\n"
            )

            proc = subprocess.run(
                [
                    str(REFRESH),
                    "--repo", str(repo),
                    "--state-dir", str(state_root),
                    "--corpus", str(corpus),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            queue = state_dir / "improvement-queue.jsonl"
            self.assertTrue(queue.exists(), "queue not written")
            rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
            kinds = [r.get("kind") for r in rows]
            self.assertIn("domain_rule_candidate", kinds)
            # The refresh JSON report should expose the count
            report = json.loads(proc.stdout)
            self.assertGreaterEqual(report.get("domain_rule_candidates_queued", 0), 1)


if __name__ == "__main__":
    unittest.main()
