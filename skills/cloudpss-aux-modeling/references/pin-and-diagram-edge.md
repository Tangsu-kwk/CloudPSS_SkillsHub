# Pin 连接与 diagram-edge 连接约定

## 结论

辅助建模参考代码的连接迁移路径是：

```text
读取画布上的 diagram-edge
→ refreshTopology()
→ deleteEdges()
→ 将每条网络边转换为元件 pin 的节点名
→ 删除 diagram-edge
→ 后续新增、修改、删除通过 pins 维护连接
```

因此，`cloudpss-aux-modeling` 不应在已经完成转换的模型中无条件创建新的 `diagram-edge`。这会混合两种连接表示，使 pin 和画布边可能不一致，也偏离 `CaseEditToolbox` / `PSAToolbox` 的原有语义。

## Skill 的运行边界

- Agent 会话初始化应遵循参考代码的转换语义，并记录转换前后的连接审计。
- 转换是有副作用的全局模型迁移，不能静默吞掉解析失败；无法解析的边、节点别名冲突或拓扑异常必须停止并报告。
- 转换完成后，新增元件的连接使用 `pins` 节点名；不因为用户在画布上表达“连接”就猜测新的 edge JSON。
- `refreshTopology()` 成功只代表当前结构被平台接受，仍需回读目标元件的 pins 和拓扑节点，不能单独宣称物理接线正确。
- 图形边查询仍然需要，但用于转换前审计、失败定位和转换后对比，不作为日常新增元件的默认连接手段。
- 只有明确选择独立的图形编辑模式并确认平台契约后，才可引入创建 diagram-edge 的接口；当前 Skill 不实现这种混合模式。

## 参考代码证据

`CaseEditToolbox.setInitialConditions()` 在 `config["deleteEdges"]` 为真时先刷新拓扑再调用 `deleteEdges()`。参考 `PSAToolbox` 的故障、断路器、输出通道和信号组件方法，新增对象均通过 `addCompInCanvas(..., pins=...)` 写入节点名，没有通过新建 `diagram-edge` 接线。

## 验收要求

测试报告必须区分：

1. 元件创建和参数回读；
2. pins 节点连接回读；
3. 拓扑节点一致；
4. 原始 diagram-edge 转换审计；
5. 仿真是否执行。

其中第 1 项通过不能替代第 2、3 项；拓扑刷新成功也不能替代仿真验证。
