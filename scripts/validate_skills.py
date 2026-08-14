#!/usr/bin/env python3
"""Validate CloudPSS Skill packages changed by a pull request.

The module deliberately uses only the Python standard library.  GitHub Actions
and contributors therefore execute the same checks without installing a
validator-specific dependency.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

REQUIRED_PATHS = ("SKILL.md", "requirements.txt", "evals/evals.json")
ALLOWED_DIRECTORIES = {"agents", "assets", "evals", "mylib", "references", "scripts"}
ALLOWED_ROOT_FILES = {
    "SKILL.md",
    "LICENSE",
    "__init__.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
}
FORBIDDEN_NAMES = {".env", ".cloudpss_token", "__pycache__", "artifacts", "results"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}

CATEGORIES = {"workflow", "analysis", "export", "inspection", "utility"}
VISIBILITIES = {"internal", "team", "public"}
# main is SimBot's live source.  Draft and experimental Skills stay outside it.
MATURITIES = {"validated"}
DEPENDENCY_STRATEGIES = {"bundled-mylib", "shared-package", "hybrid"}


@dataclass(frozen=True)
class ValidationError:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _simple_yaml_load(text: str) -> Any:
    """Parse the small mapping/list subset used by Skill frontmatter."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    index = 0

    def parse_block(indent: int) -> Any:
        nonlocal index
        mapping: dict[str, Any] = {}
        sequence: list[Any] | None = None
        while index < len(lines):
            line = lines[index]
            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation: {line}")
            stripped = line.strip()
            if stripped.startswith("- "):
                if mapping:
                    raise ValueError("cannot mix mapping and sequence at one indentation level")
                sequence = sequence if sequence is not None else []
                item = stripped[2:].strip()
                index += 1
                sequence.append(_parse_scalar(item) if item else parse_block(indent + 2))
                continue
            if sequence is not None:
                raise ValueError("cannot mix mapping and sequence at one indentation level")
            if ":" not in stripped:
                raise ValueError(f"invalid YAML line: {line}")
            key, raw_value = stripped.split(":", 1)
            key, raw_value = key.strip(), raw_value.strip()
            if not key or key in mapping:
                raise ValueError(f"empty or duplicate key: {key!r}")
            index += 1
            if raw_value:
                mapping[key] = _parse_scalar(raw_value)
            elif index < len(lines):
                next_indent = len(lines[index]) - len(lines[index].lstrip(" "))
                mapping[key] = {} if next_indent <= indent else parse_block(indent + 2)
            else:
                mapping[key] = {}
        return sequence if sequence is not None else mapping

    return parse_block(0)


def _read_frontmatter(skill_file: Path) -> tuple[dict[str, Any], str, list[ValidationError]]:
    errors: list[ValidationError] = []
    try:
        text = skill_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return {}, "", [ValidationError(skill_file, f"must be UTF-8 ({exc})")]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "", [ValidationError(skill_file, "must start with YAML frontmatter delimiter '---'")]
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, "", [ValidationError(skill_file, "frontmatter must have a closing '---' delimiter")]
    try:
        frontmatter = _simple_yaml_load("\n".join(lines[1:end]))
    except ValueError as exc:
        return {}, "", [ValidationError(skill_file, f"invalid frontmatter: {exc}")]
    if not isinstance(frontmatter, dict):
        errors.append(ValidationError(skill_file, "frontmatter must be a YAML object"))
        frontmatter = {}
    return frontmatter, "\n".join(lines[end + 1 :]).strip(), errors


def _require_string(data: dict[str, Any], key: str, path: Path, errors: list[ValidationError]) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(ValidationError(path, f"requires a non-empty '{key}'"))
        return ""
    return value.strip()


def _validate_frontmatter(skill_dir: Path, frontmatter: dict[str, Any], body: str) -> list[ValidationError]:
    path = skill_dir / "SKILL.md"
    errors: list[ValidationError] = []
    name = _require_string(frontmatter, "name", path, errors)
    description = _require_string(frontmatter, "description", path, errors)
    _require_string(frontmatter, "license", path, errors)

    if name:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(ValidationError(path, f"name must be at most {MAX_NAME_LENGTH} characters"))
        if not NAME_RE.fullmatch(name):
            errors.append(ValidationError(path, "name must use lowercase kebab-case"))
        if name != skill_dir.name:
            errors.append(ValidationError(path, f"name '{name}' must match directory '{skill_dir.name}'"))
    if len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(ValidationError(path, f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"))
    if not body or not re.search(r"^#\s+\S", body, re.MULTILINE):
        errors.append(ValidationError(path, "must contain Markdown instructions with a level-one title"))

    compatibility = frontmatter.get("compatibility")
    if not isinstance(compatibility, dict):
        errors.append(ValidationError(path, "compatibility must be a YAML object"))
        compatibility = {}
    _require_string(compatibility, "python", path, errors)
    requires_env = compatibility.get("requires_env")
    if not isinstance(requires_env, bool):
        errors.append(ValidationError(path, "compatibility.requires_env must be true or false"))
    env_vars = compatibility.get("required_env_vars")
    if not isinstance(env_vars, list) or not all(isinstance(item, str) and item.strip() for item in env_vars):
        errors.append(ValidationError(path, "compatibility.required_env_vars must be a list of non-empty strings"))
        env_vars = []
    if requires_env is True and not env_vars:
        errors.append(ValidationError(path, "requires_env=true requires at least one required_env_vars entry"))
    if requires_env is False and env_vars:
        errors.append(ValidationError(path, "requires_env=false requires an empty required_env_vars list"))
    _require_string(compatibility, "notes", path, errors)

    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        errors.append(ValidationError(path, "metadata must be a YAML object"))
        metadata = {}
    _require_string(metadata, "owner", path, errors)
    category = _require_string(metadata, "category", path, errors)
    visibility = _require_string(metadata, "visibility", path, errors)
    maturity = _require_string(metadata, "maturity", path, errors)
    entrypoint = _require_string(metadata, "entrypoint", path, errors)
    strategy = _require_string(metadata, "dependency_strategy", path, errors)
    _require_string(metadata, "verification_method", path, errors)
    shared_packages = metadata.get("shared_packages")
    if not isinstance(shared_packages, list) or not all(isinstance(item, str) and item.strip() for item in shared_packages):
        errors.append(ValidationError(path, "metadata.shared_packages must be a list of non-empty strings"))
        shared_packages = []
    if category and category not in CATEGORIES:
        errors.append(ValidationError(path, f"metadata.category must be one of {sorted(CATEGORIES)}"))
    if visibility and visibility not in VISIBILITIES:
        errors.append(ValidationError(path, f"metadata.visibility must be one of {sorted(VISIBILITIES)}"))
    if maturity and maturity not in MATURITIES:
        errors.append(ValidationError(path, "metadata.maturity must be 'validated' before entering main"))
    if strategy and strategy not in DEPENDENCY_STRATEGIES:
        errors.append(ValidationError(path, f"metadata.dependency_strategy must be one of {sorted(DEPENDENCY_STRATEGIES)}"))
    if entrypoint:
        entry_path = skill_dir / entrypoint
        if not entrypoint.startswith("scripts/verify_") or not entrypoint.endswith(".py"):
            errors.append(ValidationError(path, "metadata.entrypoint must point to scripts/verify_*.py"))
        elif not entry_path.is_file():
            errors.append(ValidationError(path, f"entrypoint does not exist: {entrypoint}"))
    if strategy in {"bundled-mylib", "hybrid"} and not (skill_dir / "mylib").is_dir():
        errors.append(ValidationError(path, f"dependency_strategy={strategy} requires mylib/"))
    if strategy in {"shared-package", "hybrid"} and not shared_packages:
        errors.append(ValidationError(path, f"dependency_strategy={strategy} requires metadata.shared_packages"))
    return errors


def _validate_evals(skill_dir: Path) -> list[ValidationError]:
    path = skill_dir / "evals" / "evals.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [ValidationError(path, f"must be valid UTF-8 JSON ({exc})")]
    if not isinstance(data, dict):
        return [ValidationError(path, "must contain a JSON object")]
    errors: list[ValidationError] = []
    if data.get("skill_name") != skill_dir.name:
        errors.append(ValidationError(path, "skill_name must match the skill directory"))
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        return errors + [ValidationError(path, "evals must be a non-empty list")]
    seen_ids: set[Any] = set()
    for index, item in enumerate(evals, start=1):
        prefix = f"eval #{index}"
        if not isinstance(item, dict):
            errors.append(ValidationError(path, f"{prefix} must be an object"))
            continue
        eval_id = item.get("id")
        if eval_id is None or eval_id in seen_ids:
            errors.append(ValidationError(path, f"{prefix} requires a unique id"))
        seen_ids.add(eval_id)
        for key in ("prompt", "expected_output"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(ValidationError(path, f"{prefix} requires a non-empty {key}"))
        expectations = item.get("expectations")
        if not isinstance(expectations, list) or not expectations or not all(
            isinstance(value, str) and value.strip() for value in expectations
        ):
            errors.append(ValidationError(path, f"{prefix} expectations must be a non-empty string list"))
    return errors


def _validate_requirements(skill_dir: Path, frontmatter: dict[str, Any]) -> list[ValidationError]:
    path = skill_dir / "requirements.txt"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return [ValidationError(path, f"must be UTF-8 ({exc})")]
    if not text.strip():
        return [ValidationError(path, "may contain only a no-dependency comment, but must not be empty")]
    errors: list[ValidationError] = []
    dependency_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    for line in dependency_lines:
        lowered = line.lower()
        if "git+" in lowered or "github.com/" in lowered:
            ref = line.rsplit("@", 1)[-1].strip().lower() if "@" in line else ""
            if not ref or ref in {"main", "master", "head", "latest"}:
                errors.append(ValidationError(path, f"VCS dependency must pin a tag or commit: {line}"))
        if lowered.startswith(("-e ", "file:", "../", "./")) or re.match(r"^[a-zA-Z]:[\\/]", line):
            errors.append(ValidationError(path, f"local path dependency is not allowed: {line}"))
    metadata = frontmatter.get("metadata", {})
    shared_packages = metadata.get("shared_packages", []) if isinstance(metadata, dict) else []
    normalized = [line.lower() for line in dependency_lines]
    for package in shared_packages if isinstance(shared_packages, list) else []:
        package_name = str(package).lower()
        if not any(line.startswith(package_name) for line in normalized):
            errors.append(ValidationError(path, f"shared package is not declared in requirements.txt: {package}"))
    return errors


def _validate_tree_and_python(skill_dir: Path) -> list[ValidationError]:
    errors: list[ValidationError] = []
    verify_scripts = list((skill_dir / "scripts").glob("verify_*.py")) if (skill_dir / "scripts").is_dir() else []
    if not verify_scripts:
        errors.append(ValidationError(skill_dir / "scripts", "requires at least one scripts/verify_*.py"))
    nested_copy = skill_dir / skill_dir.name
    if nested_copy.is_dir() and (nested_copy / "SKILL.md").exists():
        errors.append(ValidationError(nested_copy, "skill is nested one directory too deep"))
    for child in skill_dir.iterdir():
        if child.is_dir() and child.name not in ALLOWED_DIRECTORIES:
            errors.append(ValidationError(child, f"unsupported top-level directory; use one of {sorted(ALLOWED_DIRECTORIES)}"))
        elif child.is_file() and child.name not in ALLOWED_ROOT_FILES:
            errors.append(ValidationError(child, "unsupported top-level file in skill package"))
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            errors.append(ValidationError(path, "symlinks are not allowed"))
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(ValidationError(path, "sensitive, generated, or temporary content is not allowed"))
        if path.is_file() and path.suffix == ".py":
            try:
                source = path.read_text(encoding="utf-8-sig")
                ast.parse(source, filename=str(path))
            except UnicodeDecodeError as exc:
                errors.append(ValidationError(path, f"Python source must be UTF-8 ({exc})"))
            except SyntaxError as exc:
                errors.append(ValidationError(path, f"Python syntax error at line {exc.lineno}: {exc.msg}"))
    return errors


def validate_skill(skill_dir: Path) -> list[ValidationError]:
    if not skill_dir.is_dir():
        return [ValidationError(skill_dir, "changed Skill directory is missing; deletion requires a separate policy")]
    errors: list[ValidationError] = []
    for relative in REQUIRED_PATHS:
        if not (skill_dir / relative).is_file():
            errors.append(ValidationError(skill_dir / relative, "missing required file"))
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return errors
    frontmatter, body, frontmatter_errors = _read_frontmatter(skill_file)
    errors.extend(frontmatter_errors)
    if not frontmatter_errors:
        errors.extend(_validate_frontmatter(skill_dir, frontmatter, body))
    if (skill_dir / "evals" / "evals.json").is_file():
        errors.extend(_validate_evals(skill_dir))
    if (skill_dir / "requirements.txt").is_file():
        errors.extend(_validate_requirements(skill_dir, frontmatter))
    errors.extend(_validate_tree_and_python(skill_dir))
    return errors


def changed_skill_names(root: Path, base_ref: str, head_ref: str) -> list[str]:
    command = ["git", "diff", "--name-only", base_ref, head_ref, "--", "skills/"]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    names = {
        parts[1]
        for line in result.stdout.splitlines()
        if len(parts := Path(line).as_posix().split("/")) >= 3 and parts[0] == "skills"
    }
    return sorted(names)


def validate_repository(root: Path, skill_names: Iterable[str]) -> list[ValidationError]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return [ValidationError(skills_root, "skills/ directory is missing")]
    errors: list[ValidationError] = []
    for name in sorted(set(skill_names)):
        if not NAME_RE.fullmatch(name):
            errors.append(ValidationError(skills_root / name, "directory name must use lowercase kebab-case"))
            continue
        errors.extend(validate_skill(skills_root / name))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate changed CloudPSS Skill packages")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    parser.add_argument("--changed-from", help="base Git revision used to find changed Skills")
    parser.add_argument("--changed-to", default="HEAD", help="head Git revision used to find changed Skills")
    parser.add_argument("--skill", action="append", dest="skills", help="validate one named Skill; may be repeated")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.skills:
            names = sorted(set(args.skills))
        elif args.changed_from:
            names = changed_skill_names(root, args.changed_from, args.changed_to)
        else:
            parser.error("provide --changed-from or at least one --skill")
    except RuntimeError as exc:
        print(f"Unable to detect changed Skills: {exc}", file=sys.stderr)
        return 2
    if not names:
        print("Skill validation passed: no Skill directories changed.")
        return 0
    errors = validate_repository(root, names)
    if errors:
        print(f"Skill validation failed ({len(errors)} error(s)):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Skill validation passed: {len(names)} changed Skill(s) checked ({', '.join(names)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
