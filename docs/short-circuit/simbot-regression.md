# 短路电流 SimBot 回归

本地运行两份 Skill 自带的 `scripts/verify_*.py` 检查，再将 Skill 版本推到 `feat/short-circuit-simbot`。两份提示词分别见 `agent-prompt.md` 和 `agent-prompt-candidate.md`。

## 串行运行会话用例

在进程的安全环境中配置 `SIMBOT_URL` 和 `SIMBOT_API_TOKEN`。`SIMBOT_API_TOKEN` 用于 SimBot 接口授权。云端模型操作使用测试 Profile 会话内的 CloudPSS 凭据。

```text
python -B scripts/simbot_regression.py --profile PROFILE_ID --commit FULL_SHA --scenario docs/short-circuit/smoke-knowledge.json --output /path/to/evidence
```

使用 `--prompt docs/short-circuit/agent-prompt-candidate.md` 和新的证据目录运行候选提示词。默认请求从给定 SHA 加载 GitHub 插件。共享技能市场拉取失败时，可用 SimBot 的会话文件上传接口把 `git archive` 产物放到专用测试沙箱，将 `skills/` 的内容放到该工作区的 `.agents/skills/`，校验文件后传 `--sandbox-id`。对照测试沿用同一份 Skill 产物，每个提示词启动独立会话。

脚本逐轮等待完成并检查 Skill 调用和指定文件。独立检查应使用回复、事件和结果文件。知识用例需要核对指标口径和执行范围。真实 EMT 用例需要核对任务 ID、运行方案、波形、窗口与复算值。遇到发送超时先查现有会话的事件和提交回执，避免重复消息或计算。
