from __future__ import annotations

import unittest

from bin.alc_apply_contracts import validate_skill_frontmatter


class AlcApplySkillValidatorTests(unittest.TestCase):
    def test_accepts_valid_skill_frontmatter(self) -> None:
        content = "---\nname: useful-skill\ndescription: Use this skill for bounded work.\n---\n\nBody\n"
        self.assertEqual(validate_skill_frontmatter(content), [])

    def test_rejects_missing_name_and_description(self) -> None:
        errors = validate_skill_frontmatter("---\nname: x\n---\n")
        self.assertTrue(any("name must match" in error for error in errors))
        self.assertTrue(any("description is required" in error for error in errors))

    def test_rejects_overlong_description(self) -> None:
        errors = validate_skill_frontmatter(f"---\nname: useful-skill\ndescription: {'x' * 1025}\n---\n")
        self.assertTrue(any("1024" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
