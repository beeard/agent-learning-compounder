"""Tests for the shared approved-gate markdown parser."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))

import gate_registry  # noqa: E402


class GateRegistryParser(unittest.TestCase):
    def test_alias_free_markdown_returns_current_fields(self):
        blocks = gate_registry.parse_gate_blocks(
            "- domain: cloudflare\n"
            "  gate_id: 2aed10be9612\n"
            "  gate_category: docs-check\n"
            "  gate: Re-read current Cloudflare docs before changing wrangler config.\n"
            "  level: 3\n"
        )

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].domain, "cloudflare")
        self.assertEqual(blocks[0].gate_id, "2aed10be9612")
        self.assertEqual(blocks[0].gate_category, "docs-check")
        self.assertEqual(blocks[0].previous_gate_ids, [])
        self.assertEqual(blocks[0].level, "3")

    def test_previous_gate_ids_parse_as_ordered_list(self):
        blocks = gate_registry.parse_gate_blocks(
            "- domain: cloudflare\n"
            "  gate_id: cccccccccccc\n"
            "  gate_category: docs-check\n"
            "  gate: Review fresh Cloudflare docs before changing wrangler config.\n"
            "  previous_gate_ids: bbbbbbbbbbbb, aaaaaaaaaaaa\n"
        )

        self.assertEqual(blocks[0].previous_gate_ids, ["bbbbbbbbbbbb", "aaaaaaaaaaaa"])

    def test_rejects_malformed_alias(self):
        with self.assertRaisesRegex(ValueError, "previous_gate_ids"):
            gate_registry.parse_gate_blocks(
                "- domain: cloudflare\n"
                "  gate_id: cccccccccccc\n"
                "  gate_category: docs-check\n"
                "  gate: Review fresh Cloudflare docs before changing wrangler config.\n"
                "  previous_gate_ids: not-hex\n"
            )

    def test_crlf_and_no_leading_newline_parse(self):
        blocks = gate_registry.parse_gate_blocks(
            "- domain: cloudflare\r\n"
            "  gate_id: cccccccccccc\r\n"
            "  gate_category: docs-check\r\n"
            "  gate: Review fresh Cloudflare docs before changing wrangler config.\r\n"
            "  previous_gate_ids: bbbbbbbbbbbb, aaaaaaaaaaaa\r\n"
            "\r\n"
            "- domain: kubernetes\r\n"
            "  gate_id: dddddddddddd\r\n"
            "  gate_category: yaml-check\r\n"
            "  gate: Verify manifests.\r\n"
        )

        self.assertEqual([block.gate_id for block in blocks], ["cccccccccccc", "dddddddddddd"])
        self.assertEqual(blocks[0].previous_gate_ids, ["bbbbbbbbbbbb", "aaaaaaaaaaaa"])

    def test_alias_map_rejects_ambiguous_old_id(self):
        blocks = gate_registry.parse_gate_blocks(
            "- domain: one\n"
            "  gate_id: 111111111111\n"
            "  gate_category: check\n"
            "  gate: first\n"
            "  previous_gate_ids: aaaaaaaaaaaa\n"
            "- domain: two\n"
            "  gate_id: 222222222222\n"
            "  gate_category: check\n"
            "  gate: second\n"
            "  previous_gate_ids: aaaaaaaaaaaa\n"
        )

        with self.assertRaisesRegex(ValueError, "claimed by multiple"):
            gate_registry.alias_map(blocks)


if __name__ == "__main__":
    unittest.main()
