# 执行入口与计划格式

## 先执行，遇到具体缺项再读源码

入口 `scripts/model_pipeline.py` 调用同目录 `image_model_pipeline.py`，通过 `sdk_bootstrap.py` 使用 `assets/sdk/` 中的已校验 SDK wheel；不依赖开发仓库。它不识图、不推测接线、不保存项目、不提交计算。wheel 按 SHA256 解包至本机临时缓存，供脚本和 SDK 模块使用；依赖仍需安装。

### 环境、依赖与鉴权

先用实际 Python 解释器执行 `doctor`。已验证 Python 3.12.13、官方 `cloudpss==5.0.10`、自研 `automodeling==0.1.0`（导入 `auto_modeling`）与 `mirascript==0.1.103`。官方包提供 Model、鉴权和平台基础调用，自研模块提供 MCP 对应建模、检查、保存与结果能力；不要把 `automodeling` 与其他同名安装混用。

PowerShell 示例（`$skill` 为当前已加载 Skill 的实际目录，`$task` 为调用方工作区下 `outputs/<本次任务名>` 的绝对路径）：

```powershell
$python = 'python' # 换成选定解释器
$skill = (Resolve-Path 'skills/cloudpss-diagram-modeling').Path # 搬迁后改为该 Skill 的实际位置
$task = Join-Path (Get-Location) 'outputs/my_task'
$pipeline = Join-Path $skill 'scripts/model_pipeline.py'
& $python -X utf8 -B $pipeline doctor
# 依赖缺失或版本不匹配时，在任务目录建立独立环境；需可用包源。
& $python -X utf8 -B (Join-Path $skill 'scripts/setup_sdk.py') --venv (Join-Path $task '.venv')
$python = Join-Path $task '.venv/Scripts/python.exe' # Linux/macOS 为 .venv/bin/python
& $python -X utf8 -B $pipeline doctor --check-auth
& $python -X utf8 -B $pipeline import-table '输入.xlsx' --out (Join-Path $task 'materials.json')
& $python -X utf8 -B $pipeline fetch-definitions (Join-Path $task 'materials.json') --cache (Join-Path $task 'definitions.json')
& $python -X utf8 -B $pipeline build (Join-Path $task 'plan.json') --materials (Join-Path $task 'materials.json') --definitions (Join-Path $task 'definitions.json') --out (Join-Path $task 'build01')
```

`doctor` 默认不读凭据、不联网；`--check-auth` 仅检查配置是否存在，不验证令牌在线有效性。在线调用前由环境提供 `CLOUDPSS_TOKEN`、`CLOUDPSS_API_URL`；可用 `--config` 或 `AUTOMODELING_CONFIG` 指向用户自己的 YAML（`cloudpss_settings.token/api_url`），环境变量优先，相对配置路径按调用工作目录解释。不打印或复制令牌到输出。缺配置时给出具体缺项，离线材料解析和构建仍可推进。

`setup_sdk.py` 只在指定虚拟环境安装 wheel 及依赖；可加 `--plots` 安装图像渲染依赖。数值结果不依赖浏览器图像引擎；Kaleido 图片需要本机 Chrome/Chromium。旧项目迁移和自定义图形需要 Node.js >=18；`AUTOMODELING_NODE` 可指定路径。第三方依赖和可执行文件没有内置到 wheel，不能声称整包离线安装无依赖。

保存、检查、计算与结果收集使用 `scripts/project_task.py`，详见本节后文。需要其他精细操作时按 [SDK 签名索引](sdk-api.md) 导入，不重新编写整套生命周期脚本；遇到明确缺项才补通用能力。

- `import-table` 用标准库读取 XLSX，不依赖 openpyxl；读存储值，不执行公式、不以公式缓存代替结果。日期样式数值不自动解释为日期。支持每行一个参数或引脚绑定的长表，不支持合并单元格自动向下填充、任意宽表或 xls。
- 按语义找列，工作表不唯一时用 `--sheet`。特殊表头用 `--columns mapping.json`，形如 `{"id":"实例代号","definition":"库RID","key":"字段","value":"设置值"}`。未支持结构先做明确的数据适配。
- 中文默认表头：序号、元件库 RID、参数键、模型设置值；可选元件标签、图纸、位置 X,Y、字段类别、值形式。英文对应 `id/definition/key/value/label/canvas/position/group/form`。实例标识转字符串，原表 ID 不是新模型实例 ID。
- `字段类别=pins/引脚信号绑定` 放进 pins，其余视为参数组名放进 args。`值形式=expression/表达式` 保留 source；`json/结构值` 解析 JSON（保留动态表行 ɵid），其余保留单元格标量。fields 中保留原行、原值与列数据。
- 默认空值报错。材料明确空白代表空字符串时加 `--blank empty-string`；`--blank null` 仅保留 null，构建不会将其猜成零。Excel公式/错误、重复字段、实例定义冲突会中止导入。
- 空值开关不是材料补全工具。按元件类型分 sheet、每行一个实例的导出宽表需先适配成长表或 materials；保留工作表/单元格及原值，未支持的动态表结构针对性补适配，不反复尝试列映射。识别类型时只读取公开定义，不读参考模型的连接答案。
- `fetch-definitions` 是这里唯一联网命令，只读公开参数、pins、graphic，按 RID 去重，报告 hits/requests。使用环境鉴权或显式 `--config`／`AUTOMODELING_CONFIG`，不隐式读取开发仓库配置，也不输出 Token。缓存不自动刷新；需要最新定义时用新缓存。新增诊断元件也须加入定义输入，不遍历整库。
- `build` 全程离线，缺定义不联网兜底。退出码 **0**=本地参数/连接检查无问题，**2**=构建完成但有检查问题，**1**=计划/执行失败。`static_clean` 不代表平台完整 run_check 或物理正确。

## 动态表适配

对通道合并／分解器等使用动态表生成端口的元件，按公开定义和 SDK 接口适配表格数据：

- **动态表解析**：确认目标参数为表结构后，将单元格中的 JSON 文本解析为实际列表或字典，不将整段文本直接当作已生效的动态表参数。保留原始值与来源位置；解析失败时明确报出，不丢弃字段或替换为空表。
- **行字段适配**：导出表使用可读列名，而接口使用位置键或其他字段名时，依据该参数的公开列定义建立映射；保留行序、维度及已有的稳定行标识（如 `ɵid`），不按某个案例写死列号或字段对应。
- **端口身份核对**：基于适配后的实际参数生成端口，核对各行与实际端口 key 的对应关系，再建立连接；不能直接将列表下标、显示名称或行标识当作端口 key。

适配结果落实到 `工作区/outputs/<本次任务名>/materials.json` 或 `plan.json`，复用已有适配、覆盖及 `evidence` 记录保留依据与前后差异。现有入口无法表达的适配说明写入同目录 `task_record.md`，不新增专门文档。可重复的解析和字段转换优先由通用入口处理，不让每次建模重新手写，也不将本次模型的数据写入通用逻辑。

## 计划 v1

看图后直接编写数据文件，不先输出大段文字再翻译成脚本。以下仅演示格式，逻辑ID、端口与位置应来自本次材料和公开定义：

```json
{
  "schema_version": 1,
  "name": "本次模型",
  "canvases": [{"id": "main", "name": "主回路"}],
  "components": [
    {"logical_id": "source", "canvas": "main", "position": {"x": 0, "y": 0}},
    {"logical_id": "load", "canvas": "main", "position": {"x": 150, "y": 0}}
  ],
  "networks": [{
    "name": "公共节点A", "members": [["source", "p"], ["load", "p"]],
    "evidence": "主回路.png：节点A局部"
  }],
  "signals": [],
  "unresolved": []
}
```

示例需有相应 materials 记录；`logical_id` 与表格实例标识一致。无表格文件时可直接在 components 中给 definition/args/pins/label。计划不会自动导入表格全部元件：局部构建只列局部，整体验收需确认材料覆盖数量与身份。

| 字段 | 约定 |
| --- | --- |
| components | 必填 logical_id、canvas、position；definition、args、pins、label 可从材料继承。args/pins 逐键覆盖，不删除材料字段；覆盖已有值须 evidence，报告保留前后值。定义冲突需先解决材料。未知旧参数应在有依据的材料适配中明确移除并留记录，不静默丢弃 |
| size / angle / flip | 可选 size={width,height}、angle=有限角度、flip=布尔镜像。使用前端字段 angle/flip，不用 rotation/flipX/flipY；这里只验证存储，外观需单独验收 |
| networks | 电气公共节点成员，按星形生成边以保持网络等价，不还原每段视觉折线。每项须 evidence，端点须同图纸 |
| signals | source/target 为 [逻辑ID,字符串端口key]，须 evidence，可选 vertices=[{x,y},…]；不自动补反向边 |
| unresolved | 未解决的关键事实。非空时拒绝构建；另写已明确区域的局部计划，不能清空疑问假装完整 |
| parameter_groups | [{name,items:[{key,type,value,…公开参数选项}]}]，先定义表达式需要的项目参数 |
| configs | [{name,args}]，替换空白首个方案并追加；未给则保留默认方案。current_config 默认为0且须有效 |
| jobs | [{rid,name,args}]，提供后替换空白默认方案；需 `--functions functions.json` 的扁平函数定义映射。未提供的默认方案不代表已经配置工况 |

函数定义来自 `job_functions.get_job_function(rid)`，以 `{rid:返回对象}` 保存。jobs args 内显式 `{"$cell":"逻辑ID"}` 映射成新 SDK ID，可嵌在输出选择表中；普通字符串、表达式、信号名称不替换。特殊内部量测引用须明确适配，不全局替换文本。端口按求值后参数生成，再检查 condition；不支持的表达式直接报告，不猜端口。

输出 `model.json` 和 `build_report.json`：ID与图纸映射、边及依据、类型转换、已有材料值的覆盖、局部检查问题、输入 SHA256、机械执行分段时间。输出目录须新建/为空，输入不被修改。识图和编写计划耗时不包含在机械计时中。

### 任务证据与现有自动化边界

以下内容合并记入本次任务记录，复用 `fields`、`material_overrides`、`logical_to_sdk`、边的 `evidence` 与 `timing`，不要复制进不受支持的计划字段：

| 记录 | 最小内容 |
| --- | --- |
| 关键参数来源 | 实例/参数键、有效值或表达式、单位、来源位置；区分图表、方案覆盖、公开定义默认、授权参考和工程假设。覆盖值保留前后差异 |
| 实例覆盖 | 材料逻辑 ID 与 `logical_to_sdk` 比较：已建、未建、新增；未建中区分遗漏、局部范围外和有依据排除。不按标签或单一总数判断 |
| 有歧义的方向/顺序 | 实例、图片区域、箭头/符号等事实、定义端口、实际节点或信号去向；简记于已有 evidence，未确认项放 unresolved |
| 输出映射 | 通道/曲线身份、绑定元件或信号、测点、分量/相序、单位和输出采样设置；名称相同不证明物理量相同 |
| 阶段与恢复 | 起止时间、输入/模型版本、操作、检查或任务 ID、结果与重试原因；首次独立构建冻结后，另标参考引入时间 |

当前入口不会自动生成完整的参数来源/默认值审计、实例覆盖裁决、保存读回差异、生命周期计时或波形验收结论；这些仍需调用方整理或复用现有 SDK 完成。材料导入成功不等于关键参数齐全，构建成功不等于实例完整。需要扩展时针对可重复操作补通用能力及行为验证，不把本次参数、阈值或接法写进通用工具。

局部测试在任务材料中另记边界表（逻辑ID、端口/公共节点、图像出处、外部去向），不修改检查器或隐藏错误来得到0。评估时实际问题须与声明边界一致；`static_clean` 的局部模型也可能缺外部支路。通道顺序、正负极与测量方向由图片事实核对，不能仅依赖端口合法与维度相等。测试中针对本例的判据留在测试产物，不写成通用元件规则。

### 图面布局

按图交付时，先标定主要设备的相对方位、汇集层级和并行通道。构建后检查元件位置是否齐全，按实际符号尺寸和旋转状态核对包围范围，检查并行边或折线是否穿压无关设备。缺少可用尺寸或网页渲染时在任务记录注明验证范围。纯图面调整前后比较端点、参数、定义和方案；电气数据有变化时复验受影响的计算。

`build` 自动运行 `scripts/layout_audit.py`（尺寸取自 `--definitions` 的 `graphic.width/height`，缺尺寸的定义列入 `unknown_symbol_sizes` 且不参与重叠判定），报告 `missing_positions`、`overlap_count`、`canvas_extent` 与逐对重叠实例。缺位置一律判 `issues`；重叠默认只记录，交付图纸加 `--strict-layout` 使其成为失败条件。单独复查已有模型：

```powershell
& $python -X utf8 -B (Join-Path $skill 'scripts/layout_audit.py') --model build01/model.json --definitions definitions.json --out build01/layout.json --strict-layout
```

退出码 0 表示位置齐全且无重叠，2 表示发现问题。该审计只比较符号外框，直线或折线穿过无关设备需在渲染画布上人工确认；并行回路是否难以区分同样属于人工判据。

## 本地检查后：保存、计算、恢复

材料入口覆盖导入、定义缓存和离线构建；随包 `project_task.py` 复用 SDK 完成检查、显式保存、提交及按任务 ID 恢复结果。它不决定接线，不替代业务验收；下面列出实际 SDK 语义，精细操作见 [签名索引](sdk-api.md)。模块来自 `assets/sdk/` wheel；不需要原仓库源码。

```powershell
$lifecycle = Join-Path $skill 'scripts/project_task.py'
& $python -X utf8 -B $lifecycle check --model (Join-Path $task 'build01/model.json') --out (Join-Path $task 'check01.json')
# 保存/提交仅按当前任务授权执行；新 RID 先查占用，覆盖需已有授权。
& $python -X utf8 -B $lifecycle save --model (Join-Path $task 'build01/model.json') --rid 'model/account/target' --out (Join-Path $task 'save01')
& $python -X utf8 -B $lifecycle run --model (Join-Path $task 'save01/model.json') --config-index 0 --job-index 0 --out (Join-Path $task 'run01')
# run 只提交一次，随即落盘任务身份；超时或会话结束后使用原任务恢复，不能重复 run。
& $python -X utf8 -B $lifecycle collect --job-id '<真实任务ID>' --records (Join-Path $task 'run01/records.json') --out (Join-Path $task 'collect01') --timeout 30
```

`collect` 以单次有界等待取得日志及原始结果记录，按 plot key 提取数值图，不要求 Kaleido。退出码 0 仅表示结果收集完整，仍须检查 `task_status`、日志和业务数值；计算失败任务也可能有完整结果流。`snapshot`／超时不等于完成，保留同一任务继续 collect；长任务优先读取已完成结果，避免反复重放大结果流。任务异常保留失败阶段和已知身份；原项目保存与创建计算任务是不同副作用。

1. `diagram_aux.model_from_document(document)` 恢复本地模型。首次整体构建完成后必须执行下节项目级检查；`build` 的局部检查不能替代它。
2. 已授权保存用 `ProjectSession(model).save_project(target_rid)`，返回 **RID字符串**。新 RID 先只读查占用，覆盖遵守用户范围；保存后读回核对结构、参数、方案、实际定义 RID 与必要依赖/元数据。身份/版本等预期变化单列，不忽略缺失字段；发现 SDK 序列化损坏需定位修复，不能靠追加占位标签掩盖。无界面观测不声称外观通过。
3. `session.run_job(configIndex,jobIndex)` 执行预检并提交内存 revision，返回 **任务ID**，不隐式保存项目。当前入口需合法命名 RID，不给空白模型填虚构 RID 绕过前置条件。无新RID计算使用已验证的内存副本路径并核对隔离。
4. 任务ID立即落盘；异常保留 stage/outcome/revision_hash/job_id，先恢复身份再重试。已有任务缺图不等于需要重新计算。
5. `session.results.export_records()` 返回 **列表**；`import_records(records)` 恢复，`get_job_logs(job_id,True,timeout=…)` / `get_job_plots(…)` 读取。`plot_results.plot_figure(messages)` 得到数值曲线。仅任务状态不足以证明日志、流完整性与业务正确。
6. 等待期间写身份及紧凑进度，阶段结束或有恢复需求时保留完整记录，避免每轮重复写整份波形。最后 `session.close()`；失败按 [诊断与恢复](diagnosis.md) 定位。

提交计算前，核对实际任务使用的参数方案、计算方案，以及用户指定的仿真起止时间、积分步长、输出采样率和输出通道。用户未指定的设置，说明采用的默认值或选择依据。

在 `工作区/outputs/<本次任务名>/task_record.md` 中记录任务 ID 和实际提交的关键计算参数。最终报告以实际执行的工况为准；与用户要求不符时，应明确说明，不能作为指定工况下的验收结果。

重点是核对真正提交的任务输入，而不仅是脚本里原本打算使用的值。

潮流适用性、运行工况、暂态初始化与验收量由本次模型决定。函数默认值不替代用户工况；不因空白项目自带 EMT 方案就宣称计算已配置。

### 直接调用 SDK 与能力边界

需要操作入口以外的接口时，先将本 Skill 的 `scripts/` 放入 Python 模块路径，再启用随包 SDK；无需原仓库：

```python
import sys
sys.path.insert(0, str(skill_directory / 'scripts'))
from sdk_bootstrap import activate
activate()
from auto_modeling.project_session import ProjectSession
from auto_modeling.diagram_edit import add_diagram_component, add_dynamic_diagram_edge
```

本包有 83 项业务工具中的 77 项对应入口，尚无独立等价 `run_script`、`undo`、`redo`、`get_history`、`create_checkpoint`、`restore_checkpoint`。早期兼容层不作为这些能力已完成的依据。`run_check` 完整网页等价性未建立；任意旧任务结果仍受流存续期限和权限影响，不能保证仅凭任务 ID 全量恢复。SDK 不自动同步浏览器未保存状态。改动隔离使用独立内存副本与本地版本，不能称作已复现前端撤销。

已有终态任务可尝试 `job_results.import_completed_job(job_id, session=results, timeout=…)` 恢复，前提是服务仍提供结果流。失败要区分流不可用、解析错误和完整性未确认，不推广成“跨进程无法取波形”，也不凭任务状态把缺数据记为空结果。波形比较契约见 [基准差异的处理](diagnosis.md#基准差异的处理)，当前入口没有通用基准比较子命令。

## 项目级检查与报错闭环

`project_task.py check` 在原项目检查报告附上 `official_check`。CloudPSS 5.0.10 的 `Checker` 使用独立进程，按实际选定方案检查表达式和连接。明确错误或检查失败会阻止保存或新提交。`partial` 表示有未完成的检查，包括条件求值失败或官方检查器不认识定义中的端口连接类型。保留未完成阶段的诊断，结合随包检查核对受影响端口。检查输入中的缺省启用条件按启用处理，报告列出对应定义和端口。

网页 Ctrl+M 是项目级模型检查的操作入口；独立工作流使用以下 SDK 路径，不自动操作浏览器。先完成 SDK 鉴权配置，再执行：

```python
from auto_modeling.check_environment import load_check_environment
from auto_modeling.project_check import run_check

environment = load_check_environment(model)
report = run_check(model, **environment)  # 不按 groups / levels 过滤
```

将 `report` 完整写入本次输出目录的检查报告；首次报告不覆盖，修复后生成新报告。读取 `problems` 的 group、level、code、message、data，结合元件 ID 映射定位问题。按共同根因处理级联报错，逐类记录修改依据、复查结果与未解决项；error 需解决，warning 需解释，info 按影响处理。检查异常或输入加载失败保留失败阶段，不能改写为成功。只需机械修复时直接推进，不要求用户逐条处理。

`load_check_environment` 只读加载实际引用定义、函数及资源策略，不证明网页能通过项目上下文装载相同定义。`run_check` 当前保守返回 `complete:false`；报告“已查且通过 / 已查有问题 / 未覆盖”，结合 pending 和 limitations 说明影响与补验方式。影响本次计算的缺失输入须补齐；不能声称网页 Ctrl+M 已全部通过，也不因保守标记抹掉已完成检查。不要用去掉 jobs、删除元件或提供伪造环境绕过检查。

保存后将实际读回模型走同一路径复查，并核对保存前后差异。用户提供网页报错时，优先取得错误原文、对应对象和模型版本，区分定义解析、表达式、参数、拓扑及资源问题；修复后保留对应复查证据。若网页复查通道不可用，明确该项未验收，不重复宣布已清零。

定义装载按实际使用 RID、版本、权限及项目上下文追踪；预装载列表仅作为当前部署的诊断证据，不固定列表大小、订阅数量或标签占位策略。参数键合法性按平台已验证的规则判断，不把 Python `isidentifier()` 或自行编写的 ASCII 正则直接当平台契约。
