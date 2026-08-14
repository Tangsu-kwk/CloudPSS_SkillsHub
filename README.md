# CloudPSS SkillsHub

本仓库的 Skill 位于 `skills/<skill-id>/`。新增 Skill，或修改已有 Skill 时，必须
满足以下入库结构：

```text
skills/<skill-id>/
├── SKILL.md
├── requirements.txt
├── evals/
│   └── evals.json
└── scripts/
    └── verify_*.py
```

`SKILL.md` 必须包含完整的 `compatibility` 和 `metadata` 治理字段，并声明
`maturity: validated`。`requirements.txt` 没有第三方依赖时可只写
`# No third-party dependencies.`。`mylib/`、`references/`、`assets/` 和 `agents/`
按实际功能提供，不创建无用空目录。

提交 Pull Request 时，GitHub Actions 只严格检查本次新增或修改的 Skill。未改动的
历史 Skill 暂不要求迁移；以后被修改时再补齐新标准。CI 检查结构、治理字段、JSON、
依赖声明、敏感文件及 Python 语法，不运行需要 Token、网络或真实 CloudPSS 模型的
验证脚本。

本地检查某个 Skill：

```bash
python scripts/validate_skills.py --skill <skill-id>
python -m unittest discover -s scripts -p "test_*.py"
```

CI 通过只表示具备人工审核资格。最终由管理员手动合并，合并到 `main` 后 SimBot
才会自动下拉并挂载。
