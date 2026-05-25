import unittest
from typing import Any


def _minimal_v4(raw: dict[str, Any] | None = None):
    payload = {
        "event_id": "evt_manual_001",
        "ts": "2026-05-25T12:00:00+00:00",
        "event": "patch_applied",
        "actor": {
            "kind": "hook",
            "name": "collector",
            "model": "gpt-4",
        },
        "telemetry": {},
        "correlation_chain": [],
    }
    if raw:
        payload.update(raw)
    return payload


def _build_v3_row_with_missing_fields() -> dict[str, Any]:
    return {
        "ts": "2026-05-25T12:00:00+00:00",
        "event": "session_started",
        "runtime": "mcp",
        "schema_version": 3,
    }


class TestEventV4Schema(unittest.TestCase):
    def setUp(self) -> None:
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        bin_path = root / "bin"
        if str(bin_path) not in sys.path:
            sys.path.insert(0, str(bin_path))
        from event_schema import EventV4
        self.EventV4 = EventV4
        from event_schema import ActorInfo, ChainLink, Telemetry
        self.ActorInfo = ActorInfo
        self.ChainLink = ChainLink
        self.Telemetry = Telemetry

    def test_event_v4_dataclass_fields_present(self) -> None:
        event = self.EventV4(
            event_id="evt_1_a",
            ts="2026-05-25T12:00:00+00:00",
            event="patch_applied",
            actor=self.ActorInfo(kind="hook", name="h"),
            telemetry=self.Telemetry(),
            correlation_chain=[],
        )
        self.assertTrue(hasattr(event, "event_id"))
        self.assertTrue(hasattr(event, "schema_version"))
        self.assertTrue(hasattr(event, "correlation_chain"))
        self.assertEqual(event.schema_version, 4)

    def test_from_dict_validates_required_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(_minimal_v4({"event": None}))
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(_minimal_v4({"ts": None}))
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(_minimal_v4({"actor": None}))

    def test_from_dict_clamps_bounded_strings(self) -> None:
        payload = _minimal_v4(
            {
                "actor": {
                    "kind": "hook",
                    "name": "x" * 400,
                }
            }
        )
        row = self.EventV4.from_dict(payload)
        self.assertLessEqual(len(row.actor.name), 200)

    def test_from_dict_rejects_unknown_actor_kind(self) -> None:
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(
                _minimal_v4(
                    {
                        "actor": {
                            "kind": "alien",
                            "name": "bad",
                        }
                    }
                )
            )

    def test_correlation_chain_max_depth_8(self) -> None:
        payload = _minimal_v4(
            {"correlation_chain": [{"role": "x", "id": str(idx)} for idx in range(9)]}
        )
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(payload)

    def test_correlation_chain_link_id_max_128_chars(self) -> None:
        payload = _minimal_v4({"correlation_chain": [{"role": "x", "id": "y" * 200}]})
        with self.assertRaises(ValueError):
            self.EventV4.from_dict(payload)

    def test_sqlite_ddl_includes_indices(self) -> None:
        ddl = self.EventV4.sqlite_ddl()
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_events_actor_kind", ddl)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_events_event", ddl)

    def test_jsonschema_draft_7_shape(self) -> None:
        schema = self.EventV4.jsonschema()
        self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")
        self.assertIn("properties", schema)

    def test_deterministic_id_stable(self) -> None:
        first = self.EventV4.deterministic_id("hook", "patch_applied", "abc")
        second = self.EventV4.deterministic_id("hook", "patch_applied", "abc")
        self.assertEqual(first, second)

    def test_deterministic_id_differs_per_triple(self) -> None:
        a = self.EventV4.deterministic_id("hook", "patch_applied", "abc")
        b = self.EventV4.deterministic_id("hook", "patch_applied", "def")
        self.assertNotEqual(a, b)

    def test_deterministic_id_rejects_none_payload_key(self) -> None:
        with self.assertRaises(ValueError):
            self.EventV4.deterministic_id("hook", "patch_applied", None)  # type: ignore[arg-type]

    def test_upgrade_from_v3_re_enforces_boundary(self) -> None:
        bad_row = _build_v3_row_with_missing_fields()
        bad_row["path"] = "/home/user/project/secret.txt"
        bad_row["schema_version"] = 3
        with self.assertRaises(ValueError):
            self.EventV4.upgrade_from(bad_row)

    def test_upgrade_from_v3_with_missing_fields_yields_none(self) -> None:
        row = _build_v3_row_with_missing_fields()
        upgraded = self.EventV4.upgrade_from(row)
        self.assertIsNone(upgraded.telemetry.duration_ms)
