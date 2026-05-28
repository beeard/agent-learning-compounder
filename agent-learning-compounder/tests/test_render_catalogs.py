from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest


BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import render_catalogs
import analyst_queries
import recommender_generators


def write_module(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


class RenderCatalogTests(unittest.TestCase):
    def test_render_catalogs_deterministic_for_custom_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_path = root / "test_catalog_source.py"
            write_module(
                module_path,
                """
CATALOG = [
    {
        "id": "M1",
        "kind": "read",
        "summary": "read dashboard",
        "backing": "alc_query.get_gates",
        "version": 1,
    },
    {
        "id": "M2",
        "kind": "write",
        "summary": "emit recommendation",
        "backing": "reporter.emit",
        "version": 2,
    },
]
""",
            )
            sys.path.insert(0, tmp)
            try:
                out1 = root / "catalog.md"
                spec = ("test", "test_catalog_source", "CATALOG", out1)
                rendered = render_catalogs.render_all([spec])
                self.assertEqual(rendered, [(str(out1), 2)])

                rendered_text = out1.read_text(encoding="utf-8")
                self.assertIn("# test", rendered_text)
                self.assertIn("Generated from Python registry", rendered_text)
                self.assertIn("M1", rendered_text)
                self.assertIn("M2", rendered_text)

                rendered2 = render_catalogs.render_all([spec])
                rendered_text2 = out1.read_text(encoding="utf-8")
                self.assertEqual(rendered_text, rendered_text2)
            finally:
                del sys.path[0]

    def test_analyst_catalog_render_matches_checked_in_reference(self) -> None:
        rendered, count = render_catalogs._render_catalog_payload(
            "query-catalog",
            "bin.analyst_queries",
            "QUERIES",
        )
        self.assertEqual(count, len(analyst_queries.QUERIES))
        self.assertIn("| Q11 |", rendered)
        self.assertIn("| Q12 |", rendered)
        self.assertIn("query_dag_parent_child_cost", repr(analyst_queries.QUERY_FUNCS["Q11"]))

        reference = Path(__file__).resolve().parents[1] / "reference-lib" / "analyst-queries-catalog"
        self.assertEqual(reference.read_text(encoding="utf-8"), rendered)

    def test_generator_catalog_render_matches_checked_in_mirrors(self) -> None:
        rendered, count = render_catalogs._render_catalog_payload(
            "generator-catalog",
            "bin.recommender_generators",
            "GENERATORS",
        )
        self.assertEqual(count, len(recommender_generators.GENERATORS))
        self.assertIn("| G1 | anomaly_investigate |", rendered)
        self.assertIn("| G5 | workflow_chain |", rendered)
        self.assertIn("| output_class |", rendered)
        self.assertIn("patch_bundle", rendered)
        self.assertIn("suggestion", rendered)

        root = Path(__file__).resolve().parents[1]
        mirrors = [
            root / "reference-lib" / "generator-catalog",
            root / "skills" / "alc-core" / "references" / "generator-catalog.md",
        ]
        for mirror in mirrors:
            self.assertEqual(mirror.read_text(encoding="utf-8"), rendered, str(mirror))
