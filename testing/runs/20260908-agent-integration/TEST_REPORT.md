# 第三步：接口统一和 Agent 交互验收

日期：2026-09-08。模型：离线构造的 CloudPSS SDK Model，两个母线 Bus12/Bus13。LLM：deepseek/deepseek-chat。使用 newagentv2.py 自动加载三个 Skill；CloudPSS 网络入口被测试夹具禁用。本轮没有真实云端保存和仿真。

## 已完成

- 宿主通过函数 session_state 参数复用私有会话，不再硬编码辅助建模 Skill/入口名称；查询分页参数完整传递。
- 保留两个 Agent公开入口、内部 CaseEditToolbox/PSAToolbox 命名；未迁移高级场景方法明确标为不可调用。
- SKILL.md、api-contracts.md、crud-workflows.md、validation-checklist.md 统一。第一步两份盘点文档标记为历史快照。
- query新增 diagram_edge_count；不支持的 target/options字段明确拒绝，避免无效筛选被静默忽略。
- 明确只创建新 RID的保存、串行批量范围、预览ID与失效、取消、单位元数据缺失及分层状态。

## 测试证据

| 测试 | 结果 | 证据 |
|---|---|---|
| newagentv2.self_test | 三个 Skill自动发现，原有宿主离线契约通过 | 可复跑 self_test |
| 宿主工具集成 | 会话、分页、查询、预览、新增、取消、删除、原 RID保存拒绝、通用会话入口通过 | host-contract.json |
| 21模板运行时回归 | 每模板结构新增、选定字段修改、回读、删除及异常回归通过 | runtime-migration.json |
| 8轮实际LLM对话 | Bus12查询、三相电压表预览/确认新增、修改预览/取消/回读、删除预览/确认通过 | dialogue-turns.json、dialogue-events.jsonl、dialogue-snapshot-*.json、dialogue-result.json |
| 5轮扩展实际LLM对话 | 单位未核实提示、三个常量整体方案/确认串行新增、保存预览/取消通过 | extended/ 内同名证据 |

这些是真实 LLM调用真实 Skill运行时、编辑离线SDK对象的对话测试。测试器只发送普通用户句子并断言快照，未替 LLM生成工具调用。宿主契约测试则直接构造请求，两类结果分开。

首次尝试因测试器给 get_agent_final_response 传错对象而中断；模型未改动，原始记录保存在 attempt-1。修正为传事件列表后，8轮测试通过。

## 发现和修正

1. 模型摘要不列边，LLM曾从列表推断无边：增加全局 diagram_edge_count 和列表边界说明，新会话已使用该字段。
2. query曾忽略 target.canvas：现明确拒绝，宿主回归覆盖。
3. LLM根据字段名推测单位：已明确单位缺证据要标记，新会话遵守了未核实提示。

## 未完成或未通过的边界

- 真实云端读取/内存编辑/拓扑刷新未在本轮验证；离线拓扑调用故意失败，智能体如实报告。需要后续真实模型结构验收。
- 新RID实际创建、已存在/权限冲突和云端回读仍只有模拟边界测试；必须用户指定并确认目标新 RID后再做真实保存。
- 扩展对话出现“右侧空白区/不重叠”布局承诺，但实际只有坐标递进；另一次将新增回读说成增删改查均已验证。这两项回答质量不合格。已补充说明，但补充后的措辞尚未再次经过真实LLM复验。
- 批量只是逐项预览/执行，没有原子事务、整体正式预览或回滚；本次三个常量成功不证明批量失败恢复全覆盖。
- 单位/参数范围/pin方向元数据未补全；信号名是否需要 # 等工程语义未验证。pin写入不等于物理连接或仿真正确。
- 保存预览里所述能力不等于已保存。仿真与短路分析由其他 Skill负责，本轮不做。

结论：第三步的契约统一、宿主适配、离线运行时与实际LLM操作链验收完成；真实CloudPSS结构/拓扑验收及两项回复措辞复验仍待完成，不能宣布整体生产验收通过。

复跑：使用安装 CloudPSS和OpenHands的 Python运行 testing/verify_agent_modeling.py；加 --dialogue 运行8轮，另加 --extended 运行5轮。真实LLM需要环境变量 LLM_API_KEY、LLM_MODEL、LLM_BASE_URL；脚本仍禁止CloudPSS网络操作。输出会覆盖当前同名记录，复跑前归档旧证据。
