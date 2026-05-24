"""Tests for P3B-A: causal_probe register/decide CLI."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "bin" / "causal_probe"


class CausalProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_writes_probe(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.10"],
                       check=True)
        data = json.loads(self.probes.read_text())
        self.assertEqual(data["g_aaa111"]["rate"], 0.10)

    def test_decide_is_deterministic(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.10"],
                       check=True)
        out_a = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_aaa111", "--session-id", "sess-1",
        ], text=True).strip()
        out_b = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_aaa111", "--session-id", "sess-1",
        ], text=True).strip()
        self.assertEqual(out_a, out_b)
        self.assertIn(out_a, {"load", "skip"})

    def test_skip_rate_roughly_holds_over_n(self):
        """Sample size capped at 200 by default; set RUN_SLOW=1 for the 1000-iter version."""
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.30"],
                       check=True)
        import os as _os
        n = 1000 if _os.environ.get("RUN_SLOW") else 200
        delta = 0.05 if n >= 1000 else 0.08
        decisions = []
        for i in range(n):
            d = subprocess.check_output([
                str(PROBE), "--probes", str(self.probes),
                "decide", "--gate-id", "g_aaa111", "--session-id", f"s{i}",
            ], text=True).strip()
            decisions.append(d)
        skip_rate = decisions.count("skip") / len(decisions)
        self.assertAlmostEqual(skip_rate, 0.30, delta=delta)

    def test_unregistered_gate_always_loads(self):
        self.probes.write_text("{}")
        out = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_zzz", "--session-id", "sess-1",
        ], text=True).strip()
        self.assertEqual(out, "load")

    def test_unregister_removes_entry(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.10"],
                       check=True)
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "unregister", "--gate-id", "g_aaa111"],
                       check=True)
        data = json.loads(self.probes.read_text())
        self.assertNotIn("g_aaa111", data)

    def test_list_returns_all_active_probes(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_a", "--rate", "0.10"],
                       check=True)
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_b", "--rate", "0.20"],
                       check=True)
        out = subprocess.check_output([str(PROBE), "--probes", str(self.probes), "list"], text=True)
        data = json.loads(out)
        self.assertEqual(set(data.keys()), {"g_a", "g_b"})


if __name__ == "__main__":
    unittest.main()
