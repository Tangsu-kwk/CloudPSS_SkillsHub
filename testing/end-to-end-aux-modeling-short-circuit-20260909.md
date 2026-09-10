# 辅助建模到短路电流分析端到端测试报告

日期：2026-09-09  
分支：`gpt6astra-v1-0-0`

## 测试目标

从电力工程师的自然语言需求出发，验证辅助建模 Skill 能否完成元件和输出通道配置、保存新模型副本，并由短路分析 Skill 读取该副本完成 EMT 短路电流分析。

## 场景矩阵

| 场景 | 验证内容 | 结果 |
|---|---|---|
| 模板查询 | 查询元件库模板、参数和 Pin | 离线通过 |
| 单个新增 | 新增元件、设置参数、Pin 接线、预览确认 | 真实测试通过 |
| 参数修改 | 修改已有元件参数并回读 | 离线通过，真实代表性测试已有证据 |
| 元件删除 | 删除元件并清理相关结构 | 离线通过，真实代表性测试已有证据 |
| 拓扑初始化 | 图形边转换为命名 Pin并保持网络等价 | 9项离线测试通过 |
| EMT任务选择 | 列出 EMT/EMTPS 任务并要求用户选择 | 真实通过，`job_index=1` |
| 单通道配置 | 创建信号组件、设置元件信号字段、登记 `output_channels` | 真实通过 |
| 批量通道配置 | 一次预览、一次确认创建电流和电压通道 | 真实通过 |
| 重复通道复用 | 相同元件、信号类型和名称复用已有通道 | 真实会话通过 |
| 通道删除 | 删除通道组件及全部输出引用 | 真实通过 |
| 空输出组清理 | 通道删除后删除空 EMT 输出组 | 真实通过 |
| 新 RID 保存 | 只创建新 RID，不覆盖源模型 | 真实通过 |
| 保存后回读 | 回读元件、配置、jobs 和 `output_channels` | 真实通过 |
| 短路分析交接 | 新 RID 重新加载、解析故障母线和 VBase、运行 EMT | 真实通过 |
| 保存后复用 | 保存后重新加载，再次复用通道并回读 | 本轮因认证失败未完成 |

## 真实测试证据

### 通道配置和短路分析闭环

源模型：`model/Makinohara_Shoko/test1-autotest-20260909-113538-fault-analysis-ready`  
保存副本：`model/Makinohara_Shoko/test1-autotest-channel-20260909-3`

已验证：

- EMTPS 任务选择成功；
- 故障元件电流字段写入成功；
- `_newChannel` 创建和 Pin 连接成功；
- 通道登记到 EMT `output_channels` 成功；
- 保存和云端回读成功；
- 短路分析成功完成。

任务 ID：`817176ee-2b40-45dd-84bd-11ea25312b8e`

### 批量通道配置

源模型：`model/Makinohara_Shoko/IEEE39-test1`  
保存副本：`model/Makinohara_Shoko/test1-autotest-batch-20260909-1`

一次请求创建两个通道：

- `#batch_fault_current`；
- `#batch_fault_voltage`。

结果为 `requested=2`、`failed=[]`，两个通道和两个独立 EMT 输出组均通过云端回读。

### 通道删除和输出清理

保存副本：`model/Makinohara_Shoko/test1-autotest-channel-delete-20260909-5`

删除 `component_new_channel_1` 后：

- 通道组件不存在；
- 所有对应 `output_channels` 引用清除；
- 空输出组删除；
- 其他 6 个输出组保留；
- `readback_verified=true`。

## 离线测试

- `verify_runtime.py`：通过；
- `verify_migration.py`：21 个模板结构级目录、参数、Pin CRUD 通过；
- `verify_fault_connections.py`：9 项 Pin、拓扑和 `diagram-edge` 测试通过；
- `verify_runtime_contract.py`：通过；
- `verify_channel_batch_offline.py`：批量、复用基础路径和共享删除通过。

## 保存后复用未完成原因

本轮尝试使用新 Token 重新加载源模型时，CloudPSS 返回：

```text
401 INVALID_TOKEN
```

未执行后续写入，因此没有产生错误副本，也没有把该项误报为通过。该项需要在有效 Token 下补跑：

```text
创建通道
→ 保存新 RID
→ 重新加载新 RID
→ 再次请求相同通道
→ 验证 reused=true
→ 验证没有重复组件和输出组
→ 再保存并回读
```

## 结论

## 只读输出明细入口

已增加 `query_emt_outputs`。它可按 `target.job_index` 返回 EMT 输出组的名称、采样率、压缩方式、启用标记和通道组件 ID，不修改模型、不保存、不启动仿真。该入口用于在短路分析前核对“故障元件信号—通道组件—EMT 输出清单”三者是否一致。

## 诊断修正

已修正短路分析的前置错误分类：如果 `args.I` 已声明但电流单位元数据缺失，现报告为“通道存在但单位资料不足”；只有确实没有故障元件/故障母线电流声明时，才报告“没有电流通道”。安全边界不变：单位无法验证时仍不启动 EMT。

当前已经跑通并有证据支持的主链路为：

```text
自然语言建模需求
→ 元件查询/编辑
→ Pin 接线
→ EMT 任务选择
→ 输出通道配置
→ 预览确认
→ 保存新 RID
→ 云端回读
→ 短路分析读取新 RID
→ EMT 完成并返回任务 ID
```

21 个模板的结论仍应限定为结构级 CRUD 覆盖；不能扩大为全部模板均已完成真实仿真验收。辅助建模 Skill 继续不修改 EMT 步长、时长、求解器和初始条件。
