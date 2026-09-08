# 21 模板独立云端验收计划

每个 `component_cases.json` 条目使用独立会话和独立目标 RID：

1. 用户式查询模板与参数；
2. 预览并确认新增；
3. 查询回读；
4. 预览并确认参数修改；
5. 再次查询回读；
6. 预览并确认删除，核对原模型对象未变；
7. 保存当前结果到 `model/Makinohara_Shoko/test1-autotest-<template>`；
8. 独立云端 fetch 新 RID，核对新增/修改/删除结果，并记录源模型 revision 未变化。

故障电阻用例在结构验收后才交给短路分析 Skill 做预检查；若短路分析返回缺少电流通道，则由用户式对话要求辅助建模 Skill 生成通道预览，确认后保存，再重新分析。其他模板不自动添加分析通道。

每个目录保存 `turns.json`、`events.jsonl`、各轮模型快照、`save-preview.json`、`create-response.json`、`target-cloud-readback.json`、`source-before.json`、`source-after.json` 和 `result.json`。只有云端回读和源模型核对均通过，模板才计为 PASS。

历史目录 `20260907-user-dialogue` 与 `20260908-agent-integration` 不符合逐模板独立云端保存标准，只作为历史证据，不计入本轮最终通过数。
