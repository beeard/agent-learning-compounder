from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN = REPO_ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import alc_apply_contracts


def _agent_frontmatter(
    name: str = "validator-agent",
    body_word_count: int = 520,
    examples: int = 3,
    include_role: bool = True,
) -> str:
    examples_block = ""
    for idx in range(1, examples + 1):
        examples_block += textwrap.dedent(
            f"""
            <example>
            Example {idx}: deterministic workflow for bounded, auditable execution.
            </example>
            """
        )
    base_text = " ".join(["word"] * max(0, body_word_count - 30))
    role = "## Role\nThis agent performs deterministic follow-up work.\n"
    responsibilities = "## Responsibilities\nThis agent validates inputs and constraints before every change.\n"
    process = "## Process\nIt follows a bounded, auditable sequence with no speculation.\n"
    output = "## Output\nIt returns a concise, reviewable artifact every run.\n"
    if not include_role:
        sections = [responsibilities, process, output]
    else:
        sections = [role, responsibilities, process, output]
    body = "\n\n".join(sections) + "\n\n" + base_text
    return (
        "---\n"
        f"name: {name}\n"
        "description: |\n"
        + "\n".join(f"  {line}" for line in textwrap.dedent(f"""\
Use this agent when bounded follow-up is needed.

{examples_block}
""").splitlines())
        + "\n"
        "model: inherit\n"
        "color: blue\n"
        "---\n\n"
        f"{body}\n"
    )


class AlcApplyContractsTests(unittest.TestCase):
    def test_generators_targets_subset_of_dsl_targets(self) -> None:
        from recommender_generators import GENERATORS

        generated = alc_apply_contracts._extract_generator_target_types()
        self.assertLessEqual(generated, set(alc_apply_contracts.DSL_TARGETS.keys()))
        self.assertEqual(generated, {"skill", "agent"})
        self.assertIsNone(GENERATORS["workflow_chain"].target_type)

    def test_self_validation_on_import(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "bin") + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", "from bin import alc_apply_contracts"],
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_self_validation_via_main(self) -> None:
        result = subprocess.run(
            [sys.executable, str(BIN / "alc_apply_contracts.py")],
            cwd=str(REPO_ROOT),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validate_agent_frontmatter_accepts_valid(self) -> None:
        content = _agent_frontmatter()
        self.assertEqual(alc_apply_contracts.validate_agent_frontmatter(content), [])

    def test_validate_agent_frontmatter_rejects_helper_name(self) -> None:
        content = _agent_frontmatter(name="helper")
        errors = alc_apply_contracts.validate_agent_frontmatter(content)
        self.assertTrue(any("avoid generic" in error for error in errors))

    def test_validate_agent_frontmatter_rejects_too_few_examples(self) -> None:
        content = _agent_frontmatter(examples=1)
        errors = alc_apply_contracts.validate_agent_frontmatter(content)
        self.assertTrue(any("min 2" in error for error in errors))

    def test_validate_agent_frontmatter_rejects_too_many_examples(self) -> None:
        content = _agent_frontmatter(examples=5)
        errors = alc_apply_contracts.validate_agent_frontmatter(content)
        self.assertTrue(any("max 4" in error for error in errors))

    def test_validate_agent_frontmatter_rejects_short_body(self) -> None:
        content = _agent_frontmatter(body_word_count=400)
        errors = alc_apply_contracts.validate_agent_frontmatter(content)
        self.assertTrue(any("min 500" in error for error in errors))

    def test_validate_agent_frontmatter_rejects_missing_section(self) -> None:
        content = _agent_frontmatter(include_role=False)
        errors = alc_apply_contracts.validate_agent_frontmatter(content)
        self.assertTrue(any("Role" in error for error in errors))

    def test_dsl_targets_per_type_shape(self) -> None:
        for target_type, spec in alc_apply_contracts.DSL_TARGETS.items():
            self.assertIsInstance(spec.allowed_roots, list)
            self.assertGreater(len(spec.allowed_roots), 0)
            self.assertIsInstance(spec.max_size, int)
            self.assertGreater(spec.max_size, 0)
            if target_type in {"skill", "agent"}:
                self.assertTrue(callable(spec.validator))
            else:
                self.assertIsNone(spec.validator)


if __name__ == "__main__":
    unittest.main()
