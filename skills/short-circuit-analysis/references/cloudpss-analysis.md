# CloudPSS 短路分析入口

用 Skill 的实际路径运行 `scripts/analyze.py`。执行环境需具备 `requirements.txt` 中的 CloudPSS SDK。读取云端与提交使用宿主提供的凭据。入口接受 `CLOUDPSS_TOKEN`、`CLOUDPSS_LOGIN_TOKEN` 或 `SIMSTUDIO_TOKEN`。本地交接检查只读文件。

## 查活动故障或核对工作副本

```text
python -B <Skill>/scripts/analyze.py inspect --rid <model/owner/key>
python -B <Skill>/scripts/analyze.py verify --handoff <handoff.json>
```

- `inspect` 返回候选事件、EMT 计算方案及参数方案的索引和名称。故障候选包括 ID、时间、`fault_type_code` 和所选相别。三相故障电阻的 `ft=0` 为无故障。单支路事件及无法解析的相别或启用状态需要确认。只查询故障时在此交付。
- `verify` 核对导出文档摘要、参数及 EMT 方案、电流信号、同画布记录器和 EMT 输出登记。返回 `binding_verified` 代表交接一致。实际故障工况和单位还由正式入口核对。

## 提交新计算

```text
python -B <Skill>/scripts/analyze.py run --rid <model/owner/key> --fault <故障ID> --job-index <EMT方案索引> --config-index <参数方案索引> --output-dir <本次结果目录>
python -B <Skill>/scripts/analyze.py run --handoff <handoff.json> --output-dir <本次结果目录>
```

- RID 路径可显式选择两类方案。省略索引时沿用有效的当前方案。如果当前计算方案并非 EMT，只有一套 EMT 时会直接使用它，多套时要求选择。取窗、拓扑、实际提交和回执使用同一组索引。单个明确故障可省略 `--fault`。
- 工作副本路径使用交接中的故障 ID、EMT 方案和参数方案。沿用用户认可的模型工况。需要另存时，由辅助建模按用户要求另行办理。
- 直接电流以实际故障元件或故障母线声明的信号和定义中的单位为证据。通道缺失或单位不明时，指出具体缺项。单相和两相故障使用直接电流，逐通道返回指标。功率/电压等效通道对属于三相估算路径。
- 提交前在本次结果目录记录 `submission.json` 和 `analysis-context.json`。拿到 ID 后立即记录到回执。超时或中断时使用原任务 ID 和结果目录。
- 成功时标准输出为单个 `task_id` JSON。阶段日志写入标准错误。结果位于 `<本次结果目录>/<task_id>/`，可从 `task.json` 找到指标和文件。解释指标优先使用 `analysis_result.json` 和 `summary.csv`，完整波形按需读取。报告流程接收真实任务 ID，复用同一任务结果。

## 可选分析参数

`run` 接受 `--options <JSON文件>` 和 `--timeout <秒>`。故障窗默认取自目标故障的起止时间。默认分析时段来自实际提交的 EMT 方案，自定义时间窗也必须在该方案时域内。运行时按拓扑解析故障端点，三相派生计算使用模型基准电压。单相、两相和明确选定的单支路事件可在缺少基准电压时提取直接电流指标。

| 对象 | 常用字段 |
| --- | --- |
| `analysis` | `analysis_window`、`prefault_window`、`fault_window`、`postfault_window`、`steady_fault_window` 均为秒制 `[起点, 终点]`。稳态子窗也可用 `steady_fault_trim_fraction` 控制裁剪。可按需要指定 `min_samples`。 |
| `analysis` | `target_fault_id` 需与命令或交接一致。`calibration_scale` 用于有依据的额外校准，单位换算仍使用定义证据。等效估算可给 `power_scale_mw`、`voltage_scale_pu` 和 `nominal_voltage_pu`。 |
| `channels` | 先核对同一电流输出的通道唯一性和分量索引，再用 `auto_max_channels` 限制分析路数。分量数量以已验证的交接记录或元件定义为准。维度未知时仅能验证可见索引连续，且索引本身无法证明相别。已保存 RID 的等效估算使用 `equivalent_pairs`，各项以 `power` 和 `voltage` 指定同一测点对应通道。 |
| `thevenin` | `enabled` 控制派生等值计算。按需提供 `system_base_mva`、`plant_rating_mva`、`reactive_compensation_mvar`、`xr_ratio`。自定义初筛分档可给 `weak_scr_threshold`、`strong_scr_threshold`。 |

旧辅助建模引用的 `scripts/analyze_workspace.py <handoff.json> --check-only` 继续可用，等同于 `verify --handoff`。

## 查询和继续已有任务

```text
python -B <Skill>/scripts/analyze.py status --task-id <CloudPSS任务ID>
python -B <Skill>/scripts/analyze.py fetch --task-id <CloudPSS任务ID> --output-dir <目标目录>
python -B <Skill>/scripts/analyze.py resume --task-id <CloudPSS任务ID> --output-dir <原结果目录>
```

- `status` 查询服务端当前状态。`fetch` 读取已完成的 EMT 任务，把原始通道导出为 CSV 和索引。
- `resume` 用原目录的回执和分析上下文校验任务身份，按提交时保存的量测、单位和时间窗继续生成分析文件。早期任务如果只有 ID 或旧回执，使用 `fetch` 获取波形，再根据已有证据解读。
- 任务仍在运行时，`fetch` 和 `resume` 返回 `pending`。任务失败、波形流不可用或分析上下文不符时返回具体错误。这三个命令只读取已有任务。
