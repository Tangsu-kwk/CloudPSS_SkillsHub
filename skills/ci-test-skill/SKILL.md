---
name: ci-test-skill
description: Temporary Skill used to verify the repository CI workflow.
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
  entrypoint: scripts/verify_ci_test_skill.py
  dependency_strategy: bundled-mylib
  shared_packages: []
  verification_method: local_test
---

# CI Test Skill

Use this temporary Skill to verify that the repository CI accepts a complete Skill package.

## Workflow

1. Run the local verification script.
2. Check that the script returns exit code 0.
3. Return the verification result.
