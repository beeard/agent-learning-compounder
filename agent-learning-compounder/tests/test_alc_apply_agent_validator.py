from __future__ import annotations

import unittest

from bin.alc_apply_contracts import validate_agent_frontmatter


def agent_doc(**overrides) -> str:
    name = overrides.get("name", "valid-agent")
    examples = overrides.get("examples", 3)
    color = overrides.get("color", "blue")
    body_words = overrides.get("body_words", 520)
    include_role = overrides.get("include_role", True)
    description_prefix = overrides.get("description_prefix", "Use this agent when")
    example_text = "\n".join("  <example>case</example>" for _ in range(examples))
    sections = []
    if include_role:
        sections.append("## Role\nWorks deterministically.")
    sections.extend(
        [
            "## Responsibilities\nValidates every input.",
            "## Process\nRuns bounded checks.",
            "## Output\nReturns concise results.",
        ]
    )
    body = "\n\n".join(sections) + "\n\n" + " ".join(["word"] * body_words)
    return (
        "---\n"
        f"name: {name}\n"
        "description: |\n"
        f"  {description_prefix} bounded review is needed.\n"
        f"{example_text}\n"
        f"color: {color}\n"
        "model: inherit\n"
        "---\n\n"
        f"{body}\n"
    )


class AlcApplyAgentValidatorTests(unittest.TestCase):
    def test_rejects_invalid_agent_shapes(self) -> None:
        cases = [
            (agent_doc(name="helper"), "avoid generic"),
            (agent_doc(description_prefix="Run this when"), "description must start"),
            (agent_doc(examples=1), "min 2"),
            (agent_doc(examples=5), "max 4"),
            (agent_doc(body_words=400), "min 500"),
            (agent_doc(body_words=3500), "max 3000"),
            (agent_doc(include_role=False), "Role"),
            (agent_doc(color="purple"), "color"),
        ]
        for content, needle in cases:
            with self.subTest(needle=needle):
                self.assertTrue(any(needle in error for error in validate_agent_frontmatter(content)))

    def test_accepts_valid_agent(self) -> None:
        self.assertEqual(validate_agent_frontmatter(agent_doc()), [])


if __name__ == "__main__":
    unittest.main()
