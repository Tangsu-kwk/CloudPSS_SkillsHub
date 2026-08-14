import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate_skills import changed_skill_names, validate_repository


FRONTMATTER = """---
name: {name}
description: A verified example Skill used for repository validation.
license: Internal Use Only
compatibility:
  python: ">=3.11"
  requires_env: false
  required_env_vars: []
  notes: Runs locally without external credentials.
metadata:
  owner: cloudpss-team
  category: utility
  visibility: internal
  maturity: validated
  entrypoint: scripts/verify_{module}.py
  dependency_strategy: bundled-mylib
  shared_packages: []
  verification_method: local_test
---

# Demo Skill

Use the verified local workflow and return a structured result.
"""


class ValidateSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "skills").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_skill(self, name="demo-skill"):
        skill = self.root / "skills" / name
        (skill / "evals").mkdir(parents=True)
        (skill / "scripts").mkdir()
        (skill / "mylib").mkdir()
        module = name.replace("-", "_")
        (skill / "SKILL.md").write_text(FRONTMATTER.format(name=name, module=module), encoding="utf-8")
        (skill / "requirements.txt").write_text("# No third-party dependencies.\n", encoding="utf-8")
        (skill / "scripts" / f"verify_{module}.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (skill / "mylib" / "__init__.py").write_text("", encoding="utf-8")
        evals = {
            "skill_name": name,
            "evals": [
                {
                    "id": 1,
                    "prompt": "Run the demo workflow.",
                    "expected_output": "A structured success result.",
                    "files": [],
                    "expectations": ["The workflow returns a success result."],
                }
            ],
        }
        (skill / "evals" / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
        return skill

    def messages(self, name="demo-skill"):
        return [str(error) for error in validate_repository(self.root, [name])]

    def test_valid_complete_skill(self):
        self.make_skill()
        self.assertEqual(self.messages(), [])

    def test_unchanged_legacy_skills_are_not_checked(self):
        (self.root / "skills" / "legacy-skill").mkdir()
        self.assertEqual(validate_repository(self.root, []), [])

    def test_four_required_parts_are_enforced(self):
        skill = self.make_skill()
        (skill / "evals" / "evals.json").unlink()
        self.assertTrue(any("missing required file" in message for message in self.messages()))

    def test_requirements_and_verify_script_are_enforced(self):
        skill = self.make_skill()
        (skill / "requirements.txt").unlink()
        next((skill / "scripts").glob("verify_*.py")).unlink()
        messages = self.messages()
        self.assertTrue(any("requirements.txt" in message and "missing required file" in message for message in messages))
        self.assertTrue(any("requires at least one scripts/verify_*.py" in message for message in messages))

    def test_name_must_match_directory(self):
        skill = self.make_skill()
        text = (skill / "SKILL.md").read_text(encoding="utf-8").replace("name: demo-skill", "name: other-skill")
        (skill / "SKILL.md").write_text(text, encoding="utf-8")
        self.assertTrue(any("must match directory" in message for message in self.messages()))

    def test_all_governance_fields_are_required(self):
        skill = self.make_skill()
        text = (skill / "SKILL.md").read_text(encoding="utf-8").replace("  owner: cloudpss-team\n", "")
        (skill / "SKILL.md").write_text(text, encoding="utf-8")
        self.assertTrue(any("non-empty 'owner'" in message for message in self.messages()))

    def test_only_validated_maturity_can_enter_main(self):
        skill = self.make_skill()
        text = (skill / "SKILL.md").read_text(encoding="utf-8").replace("maturity: validated", "maturity: experimental")
        (skill / "SKILL.md").write_text(text, encoding="utf-8")
        self.assertTrue(any("must be 'validated'" in message for message in self.messages()))

    def test_evals_must_match_skill_and_have_expectations(self):
        skill = self.make_skill()
        path = skill / "evals" / "evals.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["skill_name"] = "other-skill"
        data["evals"][0]["expectations"] = []
        path.write_text(json.dumps(data), encoding="utf-8")
        messages = self.messages()
        self.assertTrue(any("skill_name must match" in message for message in messages))
        self.assertTrue(any("expectations must be" in message for message in messages))

    def test_verify_script_must_exist_and_compile(self):
        skill = self.make_skill()
        script = next((skill / "scripts").glob("verify_*.py"))
        script.write_text("def broken(:\n", encoding="utf-8")
        self.assertTrue(any("Python syntax error" in message for message in self.messages()))

    def test_sensitive_and_generated_files_are_rejected_recursively(self):
        skill = self.make_skill()
        (skill / "scripts" / ".env").write_text("TOKEN=secret", encoding="utf-8")
        self.assertTrue(any("not allowed" in message for message in self.messages()))

    def test_comment_only_requirements_are_allowed(self):
        self.make_skill()
        self.assertFalse(any("requirements.txt" in message for message in self.messages()))

    def test_floating_vcs_dependency_is_rejected(self):
        skill = self.make_skill()
        (skill / "requirements.txt").write_text(
            "example @ git+https://github.com/example/example.git@main\n", encoding="utf-8"
        )
        self.assertTrue(any("must pin a tag or commit" in message for message in self.messages()))

    @patch("validate_skills.subprocess.run")
    def test_changed_skill_detection_deduplicates_skill_names(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = (
            "skills/new-skill/SKILL.md\n"
            "skills/new-skill/scripts/verify_new_skill.py\n"
            "skills/updated-skill/evals/evals.json\n"
            "README.md\n"
        )
        run.return_value.stderr = ""
        self.assertEqual(
            changed_skill_names(self.root, "base", "head"),
            ["new-skill", "updated-skill"],
        )


if __name__ == "__main__":
    unittest.main()
