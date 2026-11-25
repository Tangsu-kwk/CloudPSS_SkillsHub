# 会话工作区

以 Skill 的实际绝对路径定位 `scripts/workspace.py`。在会话可持续访问的任务目录中选一个专用工作区，所有步骤沿用同一路径。逐条命令可使用新的 Python 进程。

使用 Python 3.12+。运行环境需具备随包 wheel 的依赖，版本见 `assets/sdk/requirements-tested.txt`。依赖缺失时，可在任务虚拟环境中以 `python -m pip install <Skill>/assets/sdk/automodeling-0.1.0-py3-none-any.whl` 安装。云端读取使用执行环境提供的认证，或将 `--config-file` 放在工作区参数后、子命令前。凭据保留在运行环境内。

认证优先使用 `CLOUDPSS_TOKEN`，其次为显式配置中的 Token，再依次读取宿主变量 `CLOUDPSS_LOGIN_TOKEN`、`SIMSTUDIO_TOKEN`。

以下 `<workspace>` 是会话工作区，`<cli>` 是 `scripts/workspace.py`。执行结果是 JSON。

| 动作 | 命令 |
|---|---|
| 首次读取 | `python -B <cli> <workspace> open --source <RID>`。已有本地模型时用 `open --document <model.json>`。 |
| 查看当前状态 | `python -B <cli> <workspace> inspect` 列出工作版本和方案索引。加 `--component <实例ID>` 读元件。 |
| 找实例 | `python -B <cli> <workspace> find`。可按 `--definition`、`--label`、`--canvas` 精确筛选。RID 查询定义用 SDK 的 `get_component_model`。 |
| 查端口 | `python -B <cli> <workspace> ports <实例ID>`。离线时传 `--definitions <cache.json>`。可读取定义端口和当前参数生成的端口 key。条件端口需结合实例参数检查是否启用。 |
| 查显式边 | `python -B <cli> <workspace> edges --component <实例ID>`。可加 `--port <端口key>`，返回相连的边及两端。命名 Pin 连接需结合实例绑定另查。 |
| 生成预览 | `python -B <cli> <workspace> preview <request.json>`。离线新增、改参和配置输出时提供以 RID 索引的 `--definitions <cache.json>`；配置输出还需要 `--functions <function-cache.json>`。 |
| 确认 | `python -B <cli> <workspace> apply <preview_id>`，随后用 `inspect` 读回。 |
| 导出 | `python -B <cli> <workspace> export <model.json> --handoff <handoff.json>`。生成完整工作模型和交接记录；后者包含摘要、版本、所选方案、通道及故障目标。仅导出模型时可省略 `--handoff`。 |

每个工作区保留一个待确认的预览。新预览取代旧预览。成功确认发布完整模型版本，`state.json` 包含图元、画布、`configs` 与 `jobs`。普通读写保留原模型的图形边；工作区锁阻止并发写入。如果进程在写入期间被强制结束，先确认无存活写进程，再由宿主检查并处理该工作区的残留锁。

## 故障参数

从定义取得字段键、单位和启用条件，结合当前模型中的原值填写。接口支持常量与数字字面量包装；项目变量或其他表达式需要先解决修改作用域。新值与旧有效值相同时保留原值表示。

```json
{"operation":"update_parameters","component":"实际实例ID","values":{"实际字段键":1.5},"units":{"实际字段键":"s"}}
```

修改故障电阻的 `fs` 或 `fe` 时，预览合并本次改动与实例原值，要求 `fs < fe`。已明确 EMT 方案时传 `job_index`，预览检查时间是否落在该方案的时域内。省略时沿用已绑定方案、模型当前 EMT 方案或唯一的 EMT 方案。时间来自无法直接解释的表达式时，先确认该字段在所选工况中的取值。

改变三相故障电阻的选中相别时，通过 `update_parameters` 在 `values.ft` 传入该定义中查得的字符串枚举键。预览会返回键及定义名称。相别改变后重新核对两端接法和量测登记，再导出分析交接。即使只选择一相或两相，三相故障电阻的 `I` 仍按定义的 3×1 维度登记。

## 元件增删与最终另存

- 新增请求使用 `operation: add_component`，提供 `definition`、`canvas`、`position`（`x`、`y`）及需要指定的 `label`、`args`、`pins`。预览返回按实际定义创建的元件及 ID。
- 接线请求使用 `operation: connect`，用 `source` 和 `target` 指定 `{"cell":"实际实例ID","port":"实际端口key"}`。离线时在预览命令传入定义缓存。预览先检查端口存在、画布一致和显式边重复，再按当前参数方案检查两端的启用条件、连接类型、信号方向和 X/Y 维度。预览被拒时，按返回的端口、维度或条件定位问题。接入既有网络时，还要核对相连支路和命名 Pin 绑定。
- 删除请求使用 `operation: delete_component` 和 `component`。预览列出元件及会随它移除的显式边。若方案仍引用其中任一对象，先解决引用。命名连接上的其他元件需要按实际拓扑核对。
- 另存请求使用 `operation: save_new` 和 `new_rid`，可提供 `name` 和 `desc`。确认必须针对最新工作版本。执行用官方 SDK 创建新项目并回读。只有 `status=saved` 且 `readback_verified=true` 才报告完成。工作区在提交前记录尝试；如果目标 RID 已有尝试回执，先核对结果。回读成功后，工作区仍关联原始来源，供用户继续查询和比较。

## 故障电流记录

从用户选定的故障元件定义找到电流输出字段。确认选中的 EMT 方案及参数方案，核对记录频率。已有真实信号时沿用其名称；遇到冲突时先查实际输入绑定和画布。当前入口支持有静态维度的电流输出和常规波形记录。

```json
{"operation":"configure_current","component":"实际实例ID","signal_arg":"实际电流输出字段键","signal":"本次目标电流信号名","job_index":1,"config_index":0,"sample_rate_hz":1000}
```

索引和配置值为接口示例，按实际方案及用户要求传入。已有同一画布、同输入和维度的记录器时可复用。如选择另一个工作版本或再次改参，应重新核对量测交接信息。分析副本使用短路 Skill 的 `scripts/analyze_workspace.py` 并传入该次导出的交接文件。
