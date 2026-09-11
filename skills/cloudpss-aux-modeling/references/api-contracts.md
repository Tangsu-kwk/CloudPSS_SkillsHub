# 当前接口契约

以 Skill 内部 mylib 代码为准；参考方法迁移差异列在下方。自动挂载只导出两个函数作为 Agent 工具：edit_model_from_context、inspect_model_from_context。CaseEditToolbox 和 PSAToolbox 是内部领域类。

## Agent 请求

动态工具 envelope：

```json
{
  "skill": "cloudpss-aux-modeling",
  "entrypoint": "edit_model_from_context",
  "request": {
    "operation": "query",
    "session_state": {"original_rid": "model/<owner>/<source>"},
    "target": {"identifier": "Bus12"}
  }
}
```

宿主负责提取 session_state 并持续复用会话。后续调用通常不再传 session_state。Agent只可输入 original_rid 和 api_url（认证读取环境变量）；由 Skill 的 validate_session_inputs 校验后合并。初始化后改变配置必须 initialize + options.reset=true。memory_model、toolbox、previews、result_pages禁止外部写入。宿主按参数名传 request 与 session_state；不声明输入校验器的其他 Skill只能复用内部会话，不接受外部会话配置。

| operation | target | changes/options | 确认 |
|---|---|---|---|
| initialize | 无 | options.reset=true 丢弃本地修改并重新加载 | 仅在用户要求重置时 |
| list_templates | 无 | 无；不需要模型 | 无 |
| get_template_schema | template_key | 无；不需要模型 | 无 |
| query | identifier/key/label 查询单个；definition 按类型 | options.offset=0、limit=20（1–100） | 无 |
| query_connections | identifier，可选 pin；或 node（精确 Pin 连接名） | options.offset=0、limit=20（1–100） | 无 |
| query_edges | 可选 identifier；view=original/current | options.offset=0、limit=20（1–100） | 无 |
| create | template_key、canvas；可选 key_prefix | changes.args、pins、label | 预览后确认 |
| update | identifier/key/label | changes.args、pins、label | 预览后确认 |
| delete | identifier/key/label | 无 | 预览后确认 |
| create_canvas | canvas | changes.name | 预览后确认 |
| delete_edges | 无 | 必须先刷新当前拓扑 | 预览后确认 |
| refresh_topology | 无 | 无 | 不额外确认；会提交临时 revision |
| saveProject | new_rid（完整新 RID） | changes.name、desc 可选 | 独立预览后确认 |
| cancel_preview | 无 | 请求顶层 preview_id | 无 |
| read_result | result_id | options.offset、limit（最多4000字符） | 无 |
| query_emt_jobs | 无 | 无 | 无 |
| query_emt_outputs | 可选 job_index | 无；返回 window_type、window_width_s，不能将宽度解释为启用标记 | 无 |
| configure_channel | component/identifier、job_index、signal_type、signal_arg | changes.name、channel_key、sample_rate、window_type、window_width；compression 为兼容别名 | 预览后确认 |
| configure_channels_batch | job_index | changes.channels 列表；每项 component、signal_type、signal_arg 及单通道 changes 字段 | 一次预览后确认，允许部分成功 |
| delete_channel | channel/identifier/key/label | 无 | 预览后确认 |

query 和 get_template_schema 另支持 options.fields=[参数名,...]；inspect_model_from_context支持顶层fields，仅筛选单个元件的 args。未知字段报错。省略fields读取全部；超过12000字符返回 result_id/read_request，读取分页可完整恢复JSON，缓存保留30分钟、最多8份。完整日志和模型证据由宿主保存，不把全量内容重复发给用户。

create/update 的参数必须嵌入 changes.args，不能直接放在 changes 下。模板 schema 给出字段、默认值和存储格式；缺失的工程类型、单位、范围和引脚方向返回 null，不能据此宣称物理参数校验完整。

inspect_model_from_context(session_state, identifier=None, *, offset=0, limit=20, definition=None) 是便捷查询入口：分页参数放在动态工具 request 顶层。列表只返回 key、label、definition、canvas；查询单个元件才返回 args、pins、position。列表附带全模型 diagram_edge_count，不列出图形边详情。不存在的 target/options 字段会被拒绝，不能用 target.canvas 过滤查询。

## 预览和执行

首次调用仅在拷贝上构造方案，返回 status=preview_required、preview_id、preview。用户看到的是元件名称、参数和连接方案，不必手工输入 preview_id；Agent 在用户确认后带回该 ID：

```json
{"operation":"update","preview_id":"<returned-id>","confirmation":"execute"}
```

执行必须与被确认方案一致，不得在确认时替换 target/changes/options。预览保存30分钟，最多32个；每个 ID只能执行一次。同一会话可有多个预览，但模型、配置或布局变化后旧预览失效，需要重新生成。兼容旧调用时，仅有一个同操作预览可以省略 ID；新调用始终传 ID。

成功编辑返回 status=changed、changed、current_version、saved_to_cloud=false，以及结构/拓扑/仿真分层状态。参数表达式保留 source 对象；未知参数和未知 pin 被拒绝。拓扑需另行刷新，失败不撤销已完成编辑。

批量目前为串行操作：先展示整体业务方案，确认后逐项预览、执行、回读；执行范围不得超过已确认方案。不能预先生成多个预览后连续提交，第一项提交会使剩余预览失效。失败时停止后续操作，报告已完成项、失败项及未执行项；无整体事务回滚。仅有整体业务方案，没有正式批量预览接口。

## 保存状态

saveProject 的内部实现只调用 Model.create；禁止改用 Model.save(key)（该 SDK 方法先尝试 update）。new_rid 使用 model/<owner>/<key>，key 为字母、数字、下划线或连字符；当前凭据必须有该 owner 的创建权限。目标已存在由服务端 create 拒绝；不把 fetch失败当作不存在。

| status | 含义 | 后续 |
|---|---|---|
| saved | 创建成功，回读 implements/configs/jobs 匹配 | 返回 saved_rid，可交给其他 Skill |
| saved_unverified | 创建成功但回读失败或不匹配 | 告知已创建，先排查回读，不重复创建 |
| save_failed | 收到服务端创建错误 | 报告失败，不覆盖目标 |
| save_outcome_unknown | 超时/异常/不确定响应 | 先查询目标 RID，不能自动重试写入 |

原始项目对象和 RID保持不变；保存预览在写入前即被消费，防止超时后重复提交。回读通过仅证明结构，不证明可仿真。

## 领域方法与迁移差异

方法位于 mylib/CaseEditToolbox.py，PSAToolbox 继承它。它们供 SDK开发者使用，Agent 不绕过预览直接调用。

| 方法 | 当前语义与差异 |
|---|---|
| setConfig(token=None, apiURL=None, username=None, model=None, comLibName=None, iGraph=None) | 配置认证、源模型、组件库；model 是短名称。iGraph=True 暂不支持 |
| setInitialConditions(*, project=None) | 获取项目或复用注入项目，加载库、标签和画布状态；直接调用默认 deleteEdges=True。Agent 同样默认转换；在隔离副本转换并比较前后拓扑连接分组，失败不提交，查询返回 connection_audit |
| getRevision(file=None)、loadRevision(revision=None, file=None) | revision序列化/加载；文件路径含义保留参考实现 |
| getComponentByKey、getComponentsByRid、getAllComponents | 查询实例、类型和 cells；返回 SDK对象 |
| _resolve_comp_key、_resolve_comp_keys、convertLabelToKey | 优先精确 key/label/Name；未匹配时仅对 label/Name 使用唯一大小写不敏感匹配；重名拒绝，key不做模糊匹配 |
| screenCompByArg | 按 arg、Min、Max、Set 筛选 |
| addComp(compJson, id1=None, canvas=None, position=None, args=None, pins=None, label=None) | 深拷贝模板写入 cells；新增 key冲突拒绝 |
| addCompInCanvas(compJson, key, canvas, ...) | 调用 addComp，递进坐标、避开已有 key，返回 (key,label) |
| updateCompArgs(args, compId) | 成功返回“更新成功”；失败抛异常，不再把错误作为成功字符串返回 |
| createCanvas、initCanvasPos、addxPos、newLinePos | 画布和坐标递进；不是已有图纸自动避让布局 |
| deleteComponent(compId) | 新增方法，删除普通元件和关联图形边；保留其他元件共享的节点名称 |
| refreshTopology() | 兼容 configs列表/整数索引及字典/key；更新 sa.topo，并返回 revision_hash、topology、component_count |
| deleteEdges()、getEdgeTopoPinNum() | 图形连线转命名 pins；不等于元件删除。多个节点别名等无法可靠转换时拒绝，尚不覆盖参考实现所有信号映射 |
| getConnections()、getDiagramEdges() | 只读查询当前 pin/拓扑网络及初始化前图形边审计；不创建边、不修改模型 |
| saveProject(newID, name=None, desc=None, *, confirmed=False) | newID 改为完整新 RID，confirmed=True 才能创建；返回上述结构化状态 |

故障/N-1/量测高级方法尚未迁入；可以用库中现有模板做基础 CRUD，但不能声称这些高级方法已经可调用。仿真和报告不属于本 Skill。



## 元件资料与连接查询

`get_template_schema` 从本地模板保留参数/Pin 默认值和参数 storage_type，再合并 definition RID 完全匹配的 `component-pin-schema.json` 资料。`metadata_status` 为 available、unavailable 或 definition_mismatch；available 仅表示收录了该定义的资料，不保证所有字段齐全。`metadata_evidence` 给出来源 RID 和取得日期。缺失单位等字段保持 null，不从名称猜测。choices、condition、dim、visible 保留官方原值；electrical 是连接类别，不是信号方向。当前资料不参与新增数值范围或表达式限制，物理有效性仍需另验。

例如查看变压器接法和端子：
```json
{"operation":"get_template_schema","target":{"template_key":"_newTransformer_3p2w"},"options":{"fields":["YD1","YD2","Tap"]}}
```

查询某元件端子的同网端点（编号须先查模板/实例）：
```json
{"operation":"query_connections","target":{"identifier":"Bus12","pin":"0"},"options":{"offset":0,"limit":20}}
```

`target.node` 指精确的 Pin 连接名，不是平台生成的 topology_node 编号。返回 basis、selected_pin_count、分页 items；每项含 key、label、canvas、pin、node、topology_node、selected。有最近刷新拓扑时按其节点归属查询；编辑后拓扑缓存失效，退回 named_pins_only。后者只报告同名匹配，不能据此保证跨画布的物理连通。空 Pin 不组成公共网络。查询不自动刷新；首次调用仍需正常模型初始化，初始化可能提交临时 revision 进行连接转换。

查询初始化前 Bus12 所关联的图形边：
```json
{"operation":"query_edges","target":{"identifier":"Bus12","view":"original"},"options":{"limit":20}}
```

original 是当前会话初始化转换时的历史快照，保留删除元件之前的记录，不代表当前接线。已转换模型重新加载后通常无原始快照，返回 snapshot_available=false。current 只反映当前 cells 中的图形边。两种视图都保留原始 source/target 字段；查询边分支可穿过边到边连接，不穿过元件内部。分页使用 next_offset；这两个连接查询不接受 options.fields。

离线回归：`python scripts/verify_connections.py` 覆盖连接与快照生命周期、模板资料及表达式保留；不代表云端拓扑或仿真通过。
