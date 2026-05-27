from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


def _load_distill_learning():
    loader = importlib.machinery.SourceFileLoader("distill_learning", str(BIN_DIR / "distill_learning"))
    spec = importlib.util.spec_from_loader("distill_learning", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DistillLearningStateScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = {
            "AGENT_LEARNING_USER": os.environ.pop("AGENT_LEARNING_USER", None),
            "AGENT_LEARNING_PERSONAL": os.environ.pop("AGENT_LEARNING_PERSONAL", None),
        }
        self.distill_learning = _load_distill_learning()

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_resolve_user_arg_uses_explicit_user_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "user"

            self.assertEqual(self.distill_learning.resolve_user_arg(str(root)), root.resolve())

    def test_resolve_user_arg_uses_agent_learning_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "env-user"
            os.environ["AGENT_LEARNING_USER"] = str(root)

            self.assertEqual(self.distill_learning.resolve_user_arg(None), root.resolve())

    def test_resolve_user_arg_keeps_personal_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "personal"
            os.environ["AGENT_LEARNING_PERSONAL"] = str(root)

            self.assertEqual(self.distill_learning.resolve_user_arg(None), root.resolve())

    def test_resolve_user_arg_refuses_default_for_write_gate(self) -> None:
        self.assertIsNone(self.distill_learning.resolve_user_arg(None))


if __name__ == "__main__":
    unittest.main()
