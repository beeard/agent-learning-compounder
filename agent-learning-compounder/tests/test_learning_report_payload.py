from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import distill_learning
import learning_report_payload
import render_html_report


class LearningReportPayloadTests(unittest.TestCase):
    def test_payload_filters_muted_domains_before_markdown_and_html_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            personal = pathlib.Path(tmp)
            actions = personal / "actions"
            actions.mkdir()
            (actions / "muted-domains.json").write_text(
                json.dumps([{"domain": "scope"}]),
                encoding="utf-8",
            )
            corpus = "\n".join(
                [
                    "user: scope drift, do not build UI [session_ref=s1]",
                    "user: hold scope and do not absorb adjacent work [session_ref=s2]",
                    "user: verify live runtime before answering [session_ref=s3]",
                    "assistant: deploy is probably fine [session_ref=s3]",
                ]
            )
            rules = [
                {
                    "domain": "scope",
                    "category": "scope_control",
                    "patterns": ["scope", "adjacent"],
                    "failure_signal": "scope drift",
                    "gate": "stay inside named scope",
                },
                {
                    "domain": "verification",
                    "category": "live_check",
                    "patterns": ["verify", "runtime"],
                    "failure_signal": "unverified answer",
                    "gate": "verify current runtime",
                },
            ]

            payload = learning_report_payload.build_report_payload(
                corpus,
                {"repo": "/tmp/repo"},
                "all",
                personal=personal,
                domain_rules=rules,
            )
            markdown = distill_learning.render_report(
                corpus,
                {"repo": "/tmp/repo"},
                "all",
                personal=personal,
                domain_rules=rules,
            )
            html = render_html_report.render_html_report(payload)

            domains = [row["domain"] for row in payload["memory_derived"]["rows"]]
            self.assertEqual(domains, ["verification"])
            self.assertIn("verification", markdown)
            self.assertNotIn("domain: scope", markdown)
            self.assertIn('"gates": 1', html)

    def test_markdown_and_html_consume_same_skill_and_history_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            personal = pathlib.Path(tmp)
            reports = personal / "reports" / "agent-learning"
            reports.mkdir(parents=True)
            (reports / "2026-05-27.md").write_text(
                "\n".join(
                    [
                        "## agent_compensation",
                        "### domain: verification",
                        "- level: 1-2",
                    ]
                ),
                encoding="utf-8",
            )
            corpus = "\n".join(
                [
                    "user: verify live runtime [session_ref=s1]",
                    "user: verify before final [session_ref=s2]",
                    "user: verify current state [session_ref=s3]",
                    "user: verify with tests [session_ref=s4]",
                ]
            )
            rules = [
                {
                    "domain": "verification",
                    "category": "live_check",
                    "patterns": ["verify"],
                    "failure_signal": "unverified answer",
                    "gate": "verify current runtime",
                }
            ]
            skill_map = {"skills": [{"name": "ce-work", "path": "skills/ce-work/SKILL.md"}]}
            skill_usage = {"expected": ["ce-work"], "loaded": ["ce-work"], "applied": ["ce-work"]}
            skill_impact = {
                "skills": [
                    {
                        "skill": "ce-work",
                        "impact_signal": "missed_start",
                        "candidate_adjustment": "load before plan execution",
                        "expected_sessions": 3,
                    }
                ]
            }

            payload = learning_report_payload.build_report_payload(
                corpus,
                {"repo": "/tmp/repo"},
                "all",
                personal=personal,
                skill_map=skill_map,
                skill_usage=skill_usage,
                skill_impact=skill_impact,
                domain_rules=rules,
            )
            markdown = distill_learning.render_report(
                corpus,
                {"repo": "/tmp/repo"},
                "all",
                personal=personal,
                skill_map=skill_map,
                skill_usage=skill_usage,
                skill_impact=skill_impact,
                domain_rules=rules,
            )

            self.assertEqual(payload["totals"]["gates"], 1)
            self.assertEqual(payload["totals"]["skills_available"], 1)
            self.assertIn("verification: 1-2 -> 3", payload["memory_derived"]["level_changes"][0])
            self.assertIn("level_change: verification: 1-2 -> 3", markdown)
            self.assertIn("skill: ce-work", markdown)
            self.assertIn("gate: load before plan execution", markdown)


if __name__ == "__main__":
    unittest.main()
