from __future__ import annotations

import pathlib
import re
import shutil
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import recommender_generators


try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def _parse_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError("missing frontmatter block")
    front = parts[1]
    body = parts[2]
    if yaml is not None:
        parsed = yaml.safe_load(front) or {}
        return dict(parsed), body

    parsed = {}
    for line in front.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return dict(parsed), body


class RecommenderGeneratorsTests(unittest.TestCase):
    def _temp_dir(self) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp(prefix="u9-recommender-"))
        self.addCleanup(lambda: shutil.rmtree(root))
        return root

    def test_generators_register_minimum_kinds(self) -> None:
        expected = {
            "anomaly_investigate",
            "skill_routing_review",
            "model_swap_candidate",
            "agent_spawn_suggestion",
            "workflow_chain",
        }
        self.assertEqual(set(recommender_generators.GENERATORS), expected)

    def _write_target(self, path: pathlib.Path, body: str = "agent-file\n") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_render_anomaly_routing_model_and_agent_spawn(self) -> None:
        workspace = self._temp_dir()

        anomaly_target = workspace / "skills" / "anomaly.md"
        self._write_target(anomaly_target, "Anomaly base notes.\n")
        routing_target = workspace / "skills" / "alc-core" / "notes.md"
        self._write_target(routing_target, "Routing notes.\n")
        agent_file = workspace / "agents" / "agent-swap.md"
        self._write_target(agent_file, "name: agent-swap\nmodel: inherit\n")

        samples = [
            {
                "kind": "anomaly_investigate",
                "recommendation_id": "a-1",
                "target": str(anomaly_target),
                "title": "Review anomaly",
                "details": "Model usage drift observed.",
            },
            {
                "kind": "skill_routing_review",
                "recommendation_id": "r-1",
                "target": str(routing_target),
                "title": "Review routing",
                "details": "Gate file needs a note.",
            },
            {
                "kind": "agent_spawn_suggestion",
                "recommendation_id": "s-1",
                "agent_name": "recommender-researcher",
            },
            {
                "kind": "model_swap_candidate",
                "recommendation_id": "m-1",
                "agent": str(agent_file),
                "from_model": "inherit",
                "to_model": "sonnet",
            },
        ]

        for rec in samples:
            payload = recommender_generators.render(rec)
            spec = payload["skill_manage_op"]
            if rec["kind"] == "agent_spawn_suggestion":
                self.assertIn("skill_manage_op", payload)
                self.assertIn("preflight", payload)
                self.assertIn("revert_op", payload)
                self.assertEqual(payload["skill_manage_op"]["action"], "create")
                self.assertEqual(payload["skill_manage_op"]["target_type"], "agent")
                frontmatter, body = _parse_frontmatter(payload["skill_manage_op"]["content"])
                self.assertIsInstance(frontmatter, dict)
                self.assertEqual(payload["skill_manage_op"]["target"], f"alc-agents/dev/recommender-researcher.md")
                self.assertTrue(str(frontmatter.get("name")).startswith("recommender"))
                self.assertIn("description", frontmatter)
                description = str(frontmatter.get("description"))
                self.assertTrue(description.startswith("Use this agent when"))
                example_count = len(re.findall(r"<example>", description, flags=re.IGNORECASE))
                self.assertGreaterEqual(example_count, 2)
                self.assertLessEqual(example_count, 4)
                self.assertGreaterEqual(len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", body)), 500)
                for section in ("## role", "## responsibilities", "## process", "## output"):
                    self.assertIn(section, body.lower())
            elif rec["kind"] == "model_swap_candidate":
                self.assertEqual(spec["action"], "patch")
                self.assertEqual(spec["target_type"], "agent")
                self.assertIn("model: inherit", spec["old_string"])
                self.assertIn("model: sonnet", spec["new_string"])
            else:
                self.assertEqual(spec["action"], "patch")
                self.assertEqual(spec["target_type"], "skill")
                self.assertTrue(spec["target"].startswith(str(workspace)))
                self.assertNotEqual(spec["old_string"], spec["new_string"])

            revert = payload["revert_op"]
            if spec["action"] == "patch":
                self.assertEqual(revert["action"], "patch")
                self.assertEqual(spec["target"], revert["target"])
                self.assertEqual(spec["old_string"], revert["new_string"])
                self.assertEqual(spec["new_string"], revert["old_string"])
            self.assertEqual(set(payload.keys()), {"skill_manage_op", "preflight", "revert_op"})

    def test_render_workflow_chain_is_suggestion_payload(self) -> None:
        payload = recommender_generators.render(
            {
                "kind": "workflow_chain",
                "recommendation_id": "wf-1",
                "title": "Suggested chain",
                "steps": ["a", "b", "c"],
            }
        )
        self.assertEqual(set(payload.keys()), {"suggestion"})
        suggestion = payload["suggestion"]
        self.assertEqual(suggestion["kind"], "workflow_chain")
        self.assertEqual(suggestion["title"], "Suggested chain")
        self.assertEqual(suggestion["steps"], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
