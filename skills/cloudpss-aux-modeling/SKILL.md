---
name: cloudpss-aux-modeling
description: 使用 CloudPSS 组件库进行模型元件增删改查、接线、拓扑检查和确认后保存新 RID；不执行短路仿真或报告。
metadata:
  short-description: CloudPSS 通用辅助建模
  owner: CloudPSS SkillsHub
  category: workflow
  visibility: team
  maturity: prototype
  entrypoint: scripts/verify_runtime.py
  dependency_strategy: bundled-mylib
  verification_method: offline_contract_test_and_optional_real_cloudpss_validation
  shared_packages: []
---

# CloudPSS 通用辅助建模

## 目标

帮助 Agent 在 CloudPSS 模型中进行可追踪、可验证的辅助建模。当前版本覆盖：

- 初始化一个持续复用的工作区；
- 查询元件和元件类型；
- 使用组件库新增元件；
- 修改元件参数、引脚和标签；
- 删除元件、创建画布和删除图形边；
- 回读修改结果并刷新拓扑；
- 查询组件库模板及参数/pin schema；
- 查询当前 pin 网络及初始化前的图形边审计；
- 查询当前 pin 网络及初始化前的图形边审计；
- 用户确认后只以新 RID 保存并回读。

库中的断路器、故障元件、通道和量测元件可以做基础 CRUD；故障/N-1/量测的高级场景方法尚未迁入。本 Skill 不执行仿真和结果报告。

## 工作区与安全边界

1. 认证 token 只从环境变量或用户明确提供的安全配置读取；不要写入 Skill、脚本或日志。
2. 初始化一次 `PSAToolbox`，后续连续修改复用同一个 `sa.project.revision`。只有用户要求重置或执行相互独立的批量案例时才重新初始化。
3. Agent 初始化遵循参考 `setInitialConditions()`：有图形边时先刷新拓扑、调用 `deleteEdges()` 转为命名 pins，再核验转换前后连接分组一致。仅提交验证成功的内存转换，不保存源 RID；失败停止初始化。无图形边不重复请求拓扑。查询返回 `connection_audit`，须向用户说明已转换。
4. 默认只修改当前进程中的 revision。未经用户明确授权，不调用 `saveProject()`。
5. 每次新增或修改后都查询回读；新增、删除或引脚/连接变化后调用 `refreshTopology()`。
6. 不凭记忆猜测 RID、组件 key、label 或 pin 编号；先查询当前模型和组件模板。
7. `deleteEdges()` 只负责把 `diagram-edge` 转换为 pin 名称连接。删除普通元件使用 `deleteComponent()`，预览会列出目标、关联图形边和共享节点上的其他元件；它只做结构删除，拓扑正确性要另行刷新验证。
8. “拓扑刷新成功”只表示平台接受当前结构；“最小仿真启动成功”也不等于工程上的物理连接正确。

## 标准调用流程

根据用户意图执行下列步骤，不要跳过查询和验收：

```text
确认项目和操作范围
→ 初始化 PSAToolbox
→ 查询真实 RID、key、label 和 pins
→ 使用 `edit_model_from_context` 生成带 ID 的预览
→ 用户确认后使用同一 ID 执行
→ 查询回读 definition、args、pins、canvas
→ 结构变化时 refreshTopology()
→ 用户要求保存时单独预览新 RID 并再次确认
→ 返回操作、对象标识、结构变化和验证结果
```

以下是内部领域类的初始化示例；Agent 使用下方结构化入口，不直接执行此代码：

```python
sa = PSAToolbox()
sa.config["deleteEdges"] = True
sa.setConfig(
    token=token,
    apiURL=api_url,
    username=username,
    model=model,
    iGraph=False,
)
sa.setInitialConditions()
```

## 任务路由

- 列举模板：`operation=list_templates`；用户未指定准确模板键时先调用。
- 查看模板字段：`operation=get_template_schema`，`target.template_key` 使用列表返回的精确键。返回模板默认值及已收录的官方参数、引脚资料；检查 `metadata_status` 和 `metadata_evidence`。条件引脚的 `condition`、`visible` 保留原值，不能把默认隐藏理解为引脚不存在。
- 查询模型：`operation=query`；`target.identifier/key/label` 查询单个元件，`target.definition` 按类型分页查询。
- 查询连接：`operation=query_connections`；按 `target.identifier`（可附 `pin`）或 `target.node` 查询当前 pin/拓扑节点及同网端点。
- 查询图形边：`operation=query_edges`；`target.view` 为 `original`（初始化转换前快照）或 `current`。原始快照不存在时明确返回不可用，不从删除预览猜测。
- 新增元件：`operation=create`；模板键和画布放入 `target`，参数、pins、label 放入 `changes`。
- 修改元件：`operation=update`；目标放入 `target`，只允许 `changes.args`、`changes.pins`、`changes.label`。
- 删除元件：`operation=delete`；先展示预览中的 `removed_keys` 和 `shared_net_peers`。
- 创建画布：`operation=create_canvas`；`target.canvas` 指定 key，`changes.name` 指定名称。
- 删除图形边：`operation=delete_edges`；先刷新拓扑，再预览和确认。
- 刷新拓扑：`operation=refresh_topology`，直接返回结构检查结果，不保存模型。
- 保存新副本：`operation=saveProject`；`target.new_rid` 必须是完整新 RID，名称和描述分别放在 `changes.name`、`changes.desc`。
- EMT 输出通道：先调用 `query_emt_jobs` 列出可用 EMT/EMTPS 任务，由用户选择 `job_index`；再用 `configure_channel` 创建信号组件、建立 Pin 连接并将该通道加入所选任务的独立 `output_channels` 输出组。通道创建、元件信号参数修改和输出登记统一预览确认。
- EMT 输出明细：使用只读入口 `query_emt_outputs`，可传 `target.job_index` 查询指定 EMT 任务，返回每个输出组的名称、采样率、压缩方式、启用标记和通道组件 ID；不修改模型、不保存、不启动仿真。
- 删除输出通道：使用 `delete_channel`。它会清理目标通道在所有 EMT 输出组中的引用，删除清理后为空的输出组，并删除对应 `_newChannel` 组件；其他通道保留。
- 批量输出通道：使用 `configure_channels_batch`，在同一 `job_index` 下提交 `changes.channels` 列表，一次预览、一次确认；执行结果逐项返回，允许部分成功并报告失败项。
- 保存新 RID 后运行时会强制回读模型，并校验元件结构、配置、`jobs` 及 `output_channels`。
- 取消预览：`operation=cancel_preview`，请求顶层提供 `preview_id`。
- 重置会话：仅用户要求时使用 `operation=initialize`、`options.reset=true`，会丢弃未保存修改。
- 高级故障/N-1方法未迁入，不调用不存在的方法。仿真和报告交给其他 Skill。

## 返回结果要求

不要只返回“成功”。至少报告：

```text
操作类型
组件 key 和 label
definition/RID
修改后的 args 和 pins（必要时省略敏感或过大的字段）
canvas
是否刷新拓扑及验证结果
是否创建仿真任务
是否保存云端
```

## 参考资料

- [api-contracts.md](references/api-contracts.md)：Agent 请求格式、保存状态与领域方法迁移差异。
- [component-pin-schema.json](references/component-pin-schema.json)：已收录的官方字段资料；通常通过模板查询入口按需获取，不必全文读取。
- [data-model.md](references/data-model.md)：Project、Revision、Component、cells、pins 等数据结构。
- [crud-workflows.md](references/crud-workflows.md)：初始化、查询、新增、修改和连续迭代流程。
- [validation-checklist.md](references/validation-checklist.md)：真实案例验收清单和证据等级。

## 正式可执行入口

独立 Skill 的代码位于 `mylib/`，不依赖项目根目录的 `PSAToolbox.py`。Agent 只调用以下两个公开函数：

```python
from mylib import EditRequest, edit_model_from_context

result = edit_model_from_context(
    EditRequest(operation="query"),
    session_state={"original_rid": "model/<owner>/<model>"},
)
```

`inspect_model_from_context(session_state, identifier=None, offset=0, limit=20, definition=None)` 提供分页查询。所有操作统一经 `edit_model_from_context(request, session_state)` 调度。请求字段为：

```text
operation    必填，使用任务路由列出的精确值
target       目标、模板、画布或新 RID
changes      args、pins、label、name、desc 等变更
options      query 分页或 initialize.reset
preview_id   确认或取消时使用
confirmation 确认执行时使用 execute/确认执行
```

新增、修改、删除、画布操作和保存先返回带 `preview_id` 的预览；用户确认业务方案后，由 Agent 带回同一 ID执行，用户无需手工输入 ID。预览期间模型发生变化会自动失效。保存入口仍命名为 `saveProject`，但内部只调用 `Model.create`，拒绝原 RID和当前 RID，避免覆盖。`scripts/verify_runtime.py` 和 `scripts/verify_migration.py` 是离线契约检查入口，不需要访问 CloudPSS，但需要安装 SDK。

批量为串行操作：先展示整体方案并取得确认，在确认范围内逐项生成预览、立即执行、回读；最后统一刷新拓扑。不能同时生成多个旧版本预览再依次提交。失败后停止剩余项，报告成功项、失败位置和未执行项；没有整体回滚。

模板 schema 的类型、单位、范围和 pin 方向可能缺失，不能猜测。母线 pin为空时不能宣称空连接名已完成接线。保存只有 `status=saved` 且 `readback_verified=true` 才可报告云端回读通过；其他保存状态按接口契约处理，禁止自动重复写入。

列表只列普通元件，不列图形边；`diagram_edge_count` 返回模型的图形边总数。不能根据列表里没有 edge 推断没有图形接线。未获得单位元数据时，报告参数原值并注明单位未核实；不能把依据参数名作出的解释写成平台查询事实。

列表另含 name（args.Name的原值），与图上label可能不同。identifier先精确匹配key/label/Name，再对label/Name做唯一的大小写不敏感匹配；重名仍报错。definition筛选必须是model/...类型RID，不能传diagram-edge。用户只问节点名与刷新结果时，查询目标pins并刷新即可，不遍历所有线路或用删除预览探测邻居。

当前布局只按画布坐标递进，不支持自动检测空白区域和避让。预览前不要承诺“右侧空白区”或“不重叠”；实际位置以预览为准。结果仅报告本次执行过的操作：新增与回读不能称为增删改查全部验证。

## 查询与汇报长度

用户仅问几个参数时，query 的 options.fields 或 inspect_model_from_context 的 fields 使用参数名列表，例如 ["VBase","Freq"]；模板查询 get_template_schema 也接受 options.fields。不知道字段名时先查模板。fields只筛选 args，元件标识与 pins仍返回；查询全部时省略 fields。

超过12000字符的工具结果会返回 result_id 和 read_request，完整 JSON在会话内保留30分钟（最近8份）。按 operation=read_result、target.result_id、options.offset/limit读取，每页最多4000字符，沿 next_offset直到 null。预览超长时必须读完方案后才能请求确认，不能把被隐藏的修改当作用户已经看过。模型原始数据不因输出限制而删除。

简单执行结果默认2–4行：具体对象与已完成变更、回读是否一致、拓扑状态、是否保存。不要复述全部参数、工具名、预览ID或大段流程。复杂批量用简短表格列对象和变化；失败列成功项/失败项/未执行项。用户要详情时展开。预览突出实际变更与影响，不反复输出无变化参数。仅用户询问参数含义时解释，缺少单位证据注明未核实。

单个元件执行成功时直接使用短段落，不用表格重复预览，例如：“已新增常量‘新常量’，值为5，回读一致。拓扑检查因服务不可用未完成。尚未保存云端。”只有用户明确要求详细清单时才展开。问“做了哪些验证、保存了吗”时直接回答已做/未做项目，不重复元件全量信息。当前结构化入口不支持指定或修改位置，不主动提供“调整到指定位置”的后续选项。

## 批量修改与参照元件

“把甲乙丙设为相同值”与“分别设为不同值”都先查各目标，再给整体方案，确认后逐项生成预览、立即执行并回读。失败就停止后续操作，报告部分完成，不自动回滚。预检查发现不存在、重名或不兼容目标时，先澄清，不开始执行。发生执行阶段错误时禁止跳过失败项继续。

“参数和已有元件一致”时先查询参考和目标元件，核对 definition 和字段兼容；复制用户指定的参数原值（保留 source表达式），不自动复制 Name、label、pins、位置、画布。不同类型或表达式依赖不明确时询问，不声称物理等价。修改缺省字段保持原值；新增可沿用模板默认值并说明，关键意图缺失才询问。

Skill 内部保留参考代码的领域类和方法名：`PSAToolbox(CaseEditToolbox)`、`setConfig`、`setInitialConditions`、`getComponentByKey`、`getComponentsByRid`、`addComp`、`addCompInCanvas`、`updateCompArgs`、`refreshTopology`、`deleteEdges`、`saveProject`。Agent 入口只是结构化包装，不替代这些方法。

## Pin 连接模式

参见 [pin 与图形边约定](references/pin-and-diagram-edge.md)。初始化后以 pins 节点名作为建模连接方式。新增负荷将其电气 pin 填为目标母线的实际节点名；线路两端填写目标网络节点名。不要因画布没有新增线条就判定没有电气连接，也不要承诺创建 diagram-edge。端子用途未知时查询证据，不猜变压器端子顺序。比较拓扑中目标 pin 的节点归属验证连接，节点编号本身可能变化。
