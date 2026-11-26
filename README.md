# CloudPSS SkillsHub

本仓库的 Skill 放在 `skills/<skill-id>/` 下，一个目录一个 Skill，目录名就是 Skill 名。
SimBot 从本仓库 `main` 分支拉取 Skill 并挂载。

每个 Skill 至少包含 `SKILL.md`，其中用 YAML frontmatter 写明 `name` 与 `description`。
其余目录按该 Skill 的实际功能提供，仓库对目录组成不做统一约定：

- `scripts/`：可执行入口与辅助脚本
- `references/`：按需加载的说明、契约与数据
- `assets/`：随包携带的依赖或数据文件
- `agents/`：客户端展示配置
- `mylib/`、`evals/`：个别 Skill 自带

现有 Skill 见 `skills/` 目录。
