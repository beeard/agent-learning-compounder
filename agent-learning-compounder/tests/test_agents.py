import pathlib
import re
import unittest

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_FILE = ROOT / "agents" / "alc-reviewer.md"
CLAUDE_YAML = ROOT / "agents" / "claude.yaml"
OPENAI_YAML = ROOT / "agents" / "openai.yaml"

ALLOWED_COLORS = {"blue", "cyan", "green", "yellow", "red", "magenta"}
MIN_BODY_WORDS = 500
MAX_BODY_WORDS = 3000


def _parse_frontmatter_raw(path):
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Missing YAML frontmatter block")
    front = parts[1]
    body = parts[2]
    if yaml is not None:
        fm = yaml.safe_load(front) or {}
    else:
        fm = _fallback_parse_frontmatter(front)
    return fm, body


def _fallback_parse_frontmatter(front):
    fm = {}
    lines = front.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            i += 1
            block = []
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                block.append(lines[i].lstrip(" \t"))
                i += 1
            fm[key] = "\n".join(block)
            continue
        if value.startswith("[") and value.endswith("]"):
            fm[key] = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        else:
            fm[key] = value.strip("\"'")
        i += 1
    return fm


def _parse_agent_mappings(path):
    if yaml is not None:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agents = cfg.get("agents")
        if isinstance(agents, list):
            return [
                {"name": item.get("name"), "persona": item.get("persona")}
                for item in agents
                if isinstance(item, dict)
            ]

    text = path.read_text(encoding="utf-8")
    in_agents = False
    entries = []
    current = None
    for line in text.splitlines():
        if re.match(r"^agents:\s*$", line):
            in_agents = True
            continue
        if in_agents and re.match(r"^\S", line):
            in_agents = False
            if current:
                entries.append(current)
                current = None
            continue
        if not in_agents:
            continue
        m_name = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m_name:
            if current:
                entries.append(current)
            current = {"name": m_name.group(1)}
            continue
        m_persona = re.match(r"^\s*persona:\s*(.+?)\s*$", line)
        if current is not None and m_persona:
            current["persona"] = m_persona.group(1)
    if current:
        entries.append(current)
    return entries


def _body_sections_present(body):
    sections = ("Role", "Responsibilities", "Process", "Output")
    normalized = body.lower()
    for section in sections:
        if section.lower() not in normalized:
            return False
    return True


class TestAgents(unittest.TestCase):
    def test_agent_frontmatter_required_fields(self):
        frontmatter, _body = _parse_frontmatter_raw(AGENT_FILE)
        self.assertEqual(frontmatter.get("name"), "alc-reviewer")
        self.assertIn("description", frontmatter)
        self.assertIn("color", frontmatter)
        self.assertIn(frontmatter.get("model"), {"inherit", "sonnet", "haiku", "opus"})

    def test_agent_description_examples_and_prefix(self):
        frontmatter, _body = _parse_frontmatter_raw(AGENT_FILE)
        description = (frontmatter.get("description") or "").strip()
        self.assertTrue(description.startswith("Use this agent when"))
        example_count = len(re.findall(r"<example>", description, flags=re.IGNORECASE))
        self.assertGreaterEqual(example_count, 2)
        self.assertLessEqual(example_count, 4)

    def test_agent_body_sections_present(self):
        _frontmatter, body = _parse_frontmatter_raw(AGENT_FILE)
        self.assertTrue(_body_sections_present(body))

    def test_agent_body_word_count(self):
        _frontmatter, body = _parse_frontmatter_raw(AGENT_FILE)
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", body)
        self.assertGreaterEqual(len(words), MIN_BODY_WORDS)
        self.assertLessEqual(len(words), MAX_BODY_WORDS)

    def test_agent_color_in_allowed_set(self):
        frontmatter, _body = _parse_frontmatter_raw(AGENT_FILE)
        self.assertIn(frontmatter.get("color"), ALLOWED_COLORS)

    def test_yaml_mappings_reference_alc_reviewer_by_path(self):
        for mapping_file in (CLAUDE_YAML, OPENAI_YAML):
            entries = _parse_agent_mappings(mapping_file)
            reviewer_entries = [
                item
                for item in entries
                if str(item.get("name")).strip().lower() == "alc-reviewer"
            ]
            self.assertEqual(len(reviewer_entries), 1)
            persona = (reviewer_entries[0].get("persona") or "").strip()
            self.assertIn(persona, {"./agents/alc-reviewer.md", "agents/alc-reviewer.md"})
            self.assertEqual(mapping_file.read_text(encoding="utf-8").count("name: alc-reviewer"), 1)

    def test_yaml_mappings_do_not_reference_removed_agents(self):
        for mapping_file in (CLAUDE_YAML, OPENAI_YAML):
            text = mapping_file.read_text(encoding="utf-8").lower()
            self.assertNotIn("alc-analyst", text)
            self.assertNotIn("alc-recommender", text)


if __name__ == "__main__":
    unittest.main()
