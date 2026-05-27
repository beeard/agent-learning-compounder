import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from bin import alc_eval
from bin.state_handle import StateHandle


class AlcEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.state_root = pathlib.Path(self.tmp.name) / "state"
        self.env = mock.patch.dict(os.environ, {"AGENT_LEARNING_STATE_DIR": str(self.state_root)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state = StateHandle.for_repo(self.repo)
        self.state.alc_agents_dirs["evals"].mkdir(parents=True, exist_ok=True)
        (self.state.alc_agents_dirs["evals"] / "rec-quality-judge.md").write_text("---\nname: rec-quality-judge\n---\n", encoding="utf-8")

    def _events(self):
        return [json.loads(line) for line in (self.state.events_jsonl).read_text(encoding="utf-8").splitlines()]

    def test_eval_emits_verdict_for_each_recommendation(self):
        recs = [
            {"id": "r1", "kind": "skill", "ts": "2026-05-25T00:00:00+00:00"},
            {"id": "r2", "kind": "skill", "ts": "2026-05-25T00:00:00+00:00"},
            {"id": "r3", "kind": "agent", "ts": "2026-05-25T00:00:00+00:00"},
        ]
        outputs = [
            {"output": '{"verdict":"approve","judge_reason":"good"}'},
            {"output": '{"verdict":"reject","judge_reason":"weak"}'},
            {"output": '{"verdict":"modify","judge_reason":"needs edits"}'},
        ]
        with mock.patch.object(alc_eval, "get_recommendations", return_value=recs), mock.patch.object(
            alc_eval, "invoke", side_effect=outputs
        ):
            code, written = alc_eval.run(repo=self.repo, window="7d", limit=20, judge="evals/rec-quality-judge")

        self.assertEqual((code, written), (0, 3))
        events = self._events()
        self.assertEqual(len(events), 3)
        self.assertEqual({event["event"] for event in events}, {"eval_verdict"})
        self.assertEqual({event["payload"]["verdict"] for event in events}, {"approve", "reject", "modify"})
        self.assertEqual(events[0]["actor"]["kind"], "eval_judge")
        self.assertEqual(events[0]["actor"]["name"], "rec-quality-judge")
        self.assertEqual(events[0]["correlation_chain"], [{"role": "evaluated_rec", "id": "r1"}])
        self.assertEqual(events[0]["payload"]["lifecycle"]["proposal_kind"], "eval")
        self.assertEqual(events[0]["payload"]["lifecycle"]["recommendation_id"], "r1")

    def test_rerun_skips_existing_deterministic_events(self):
        recs = [{"id": "r1", "kind": "skill", "ts": "2026-05-25T00:00:00+00:00"}]
        with mock.patch.object(alc_eval, "get_recommendations", return_value=recs), mock.patch.object(
            alc_eval, "invoke", return_value={"output": '{"verdict":"approve","judge_reason":"ok"}'}
        ):
            self.assertEqual(alc_eval.run(repo=self.repo, window="7d", limit=20, judge="evals/rec-quality-judge"), (0, 1))
            before = (self.state.events_jsonl).read_text(encoding="utf-8")
            self.assertEqual(alc_eval.run(repo=self.repo, window="7d", limit=20, judge="evals/rec-quality-judge"), (0, 0))
            after = (self.state.events_jsonl).read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_limit_zero_noop(self):
        with mock.patch.object(alc_eval, "get_recommendations") as get_recs, mock.patch.object(alc_eval, "invoke") as invoke:
            self.assertEqual(alc_eval.run(repo=self.repo, window="7d", limit=0, judge="evals/rec-quality-judge"), (0, 0))
        get_recs.assert_not_called()
        invoke.assert_not_called()

    def test_missing_judge_exits_one(self):
        self.assertEqual(alc_eval.run(repo=self.repo, window="7d", limit=20, judge="evals/missing"), (1, 0))

    def test_malformed_judge_json_defaults_modify(self):
        recs = [{"id": "r1", "kind": "skill", "ts": "2026-05-25T00:00:00+00:00"}]
        with mock.patch.object(alc_eval, "get_recommendations", return_value=recs), mock.patch.object(
            alc_eval, "invoke", return_value={"output": "not json"}
        ):
            self.assertEqual(alc_eval.run(repo=self.repo, window="7d", limit=20, judge="evals/rec-quality-judge"), (0, 1))
        event = self._events()[0]
        self.assertEqual(event["payload"]["verdict"], "modify")
        self.assertIn("malformed JSON", event["payload"]["judge_reason"])


if __name__ == "__main__":
    unittest.main()
