# 辅助建模业务任务测试记录

宿主：SCAgent2/newagentv2.py；真实 LLM：deepseek/deepseek-chat。该名称不能等同于尚未确认配置的部署端 DeepSeek V4 Flash。
自动加载辅助建模、短路分析、报告三个 Skill；不调用报告生成 Skill。专业代码和宿主保持原样，测试器仅发送自然语言、观察与核验模型。
云端只允许创建本轮指定新 RID；每个修改版和删除版单独保存并完整回读 implements、parameters、pins、configs、jobs。
所有原模型 cells 每轮比对；每个任务结束独立 fetch 原模型。配置、元件 schema 缺少的物理含义不因拓扑刷新成功而认定正确。

## 任务状态

| 任务 | 新增 | 修改 | 删除 | 拓扑 | 云端版本数 | 总体状态 |
|---|---|---|---|---|---|---|
| 批量负荷与参照参数修改 | verified | verified | verified | refreshed_not_physical_validation | 2 | structural_pass |
| 常量—增益—输出通道及取消修改 | verified | verified | verified | refreshed_not_physical_validation | 2 | structural_pass |
| fault | 未验证 | 未验证 | 未验证 | 未验证 | 0 | running |
| 母线—线路—负荷支路 | 未验证 | 未验证 | 未验证 | 未验证 | 0 | failed_or_blocked |
| 变压器两侧母线接线 | 未验证 | 未验证 | 未验证 | 未验证 | 0 | failed_or_blocked |

## 阅读边界

- 任务失败按具体阶段记录；运行时错误、模型澄清、测试断言和服务故障分开分析，不按条目数量算通过。
- 结构成功不等于正确的端子语义；拓扑刷新也不等于 EMT 成功或物理结果合理。
- 变压器、故障等需要端子含义的任务可能因 schema 缺失受阻；不得猜端子后计通过。
- 模板枚举并非本轮目标；以组合业务需求为主要验收单位。
- 本轮结果不能替代所有元件、参数范围、边界条件或仿真场景覆盖。

## 逐任务详录

- [batch-load](batch-load/TEST_REPORT.md)
- [control](control/TEST_REPORT.md)
- [fault](fault/TEST_REPORT.md)
- [feeder](feeder/TEST_REPORT.md)
- [transformer](transformer/TEST_REPORT.md)
