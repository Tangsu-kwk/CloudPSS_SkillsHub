# 用户交互与 CRUD 工作流

用户只需说需求；模板 key、args、pin 编号和 preview_id 由 Agent 查询并管理。

## 在 Bus12 上加三相电压表

用户：“帮我在 Bus12 上加一个三相电压表，输出叫 bus12_voltage。”

1. 若没有源模型 RID，先向用户取得 RID；已有会话直接复用。
2. query 查 Bus12，list_templates 查可用模板，get_template_schema 查选中模板字段。
3. 从回读获取画布、母线连接名和模板 pin；如母线 pin为空，不能把空字符串当已接线。应检查图形边/拓扑转换能力，无法可靠确定连接时报告缺口。
4. 根据模板真实字段构造 create，预览说明“新增什么、接到哪里、哪些参数变化”。
5. 用户：“就这样加。”Agent 带回 preview_id 执行，查询新增实例回读，再 refresh_topology。
6. 报告结构编辑、拓扑结果及未保存状态。电压表不自动代表已经配置输出通道或运行仿真。

## 修改与删除

用户：“把刚才的电压表改成……”
先按上次返回 key回读，使用 update 的 changes.args/pins/label。参数缺少单位依据时先明确含义，不凭默认字符串猜单位。

用户：“删掉刚才的电压表。”
用 delete 预览展示被删除实例、关联图形边、共享节点上的其他元件。确认后执行，query检查目标不再存在，再刷新拓扑。不得用 delete_edges 代替 delete。

重名时使用错误中的候选 key让用户区分。非法字段时重新查 schema；不得用临时 Python代码绕过校验。

## 串行批量

用户：“加三个常量，数值分别是1、2、3。”
查模板，给出含三项名称、数值、画布的整体方案。用户确认整个方案后，在已确认范围内逐项调用 create预览并立即确认执行、回读，再处理下一项，最后统一刷新拓扑。

每次正式预览产生新 ID；不复用其他项 ID，不执行因前项修改而失效的旧预览。中途失败即停止，报告成功项/失败位置/未执行项。没有底层批量事务或整体回滚；用户改变方案时重新确认改变部分。

## 新 RID 保存

用户：“把这个修改后的模型保存到 model/<owner>/<new_key>。”
用 saveProject + target.new_rid 生成保存预览，说明源 RID、目标 RID、只创建、当前结构/拓扑验证状态。用户确认后执行。

仅 status=saved 且 readback_verified=true 时说明云端回读已通过并返回 saved_rid。saved_unverified/unknown 先核查，不能宣称完成，也不能自动重复写入。把保存后的 RID交给短路分析 Skill；辅助建模不执行短路分析。

## 会话

连续修改复用宿主私有 session_state，内部领域对象是 sa.project。进程重启会丢失未保存修改和预览。

用户要求重新加载或切换源模型时，通过 initialize + options.reset=true，并在 session_state.original_rid 提供源 RID。不要把保存目标 RID写入 original_rid，否则会误切换工作区。
