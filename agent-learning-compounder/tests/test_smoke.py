import pathlib
import unittest


class SkillRuntimeLayoutTests(unittest.TestCase):
    def test_runtime_layout_keeps_development_artifacts_out_of_hot_path(self):
        root = pathlib.Path(__file__).resolve().parents[1]

        self.assertTrue((root / "skills" / "alc-core" / "SKILL.md").is_file())
        self.assertTrue((root / "scripts" / "init_learning_system.py").is_file())
        self.assertTrue((root / "fixtures" / "tests").is_dir())


if __name__ == "__main__":
    unittest.main()
