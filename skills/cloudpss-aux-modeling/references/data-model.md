# CloudPSS 数据结构

## 标识层次

```text
模型路径：model/<username>/<model>
组件类型：RID，例如 model/CloudPSS/TransmissionLine
组件实例：key/id，例如 canvas_0_105
显示名称：label，例如 TLine_3p-40
```

不要混淆它们：同一个 RID 可以有多个实例；label 可能变化；key 是当前 revision 中的实例标识。

## `Component`

`Component` 由组件 JSON 初始化，主要字段如下：

```python
component.id          # 实例 key
component.label       # 图上显示标签
component.definition  # 组件类型 RID
component.canvas      # 所在画布 key
component.args        # 参数字典
component.pins        # 端口编号到拓扑连接名的字典
component.shape       # diagram-component 或 diagram-edge
component.position    # 图形坐标
```

`component.pins` 的 key 是组件端口编号，value 是连接节点名。三相母线通常有一个复合电气端口 `"0"`；多个元件可以把该端口写成同一个节点名，例如 `bus37`，表示它们接在同一拓扑节点，不代表母线有很多独立 pin。

## `Project`、`Revision` 和 `diagram`

```text
sa.project
└── revision
    └── implements
        └── diagram
            ├── cells   # 实例 key → Component，包含元件和图形边
            └── canvas   # 画布定义列表
```

`sa.project.revision` 是本轮工作区中的版本对象。`addComp()` 写入 `diagram.cells` 后，修改只存在于当前进程；`refreshTopology()` 会提交临时 revision 给拓扑接口；`saveProject()` 才是持久化到云端的新算例。

## 图形连接与逻辑连接

- `diagram-edge`：画布上的图形连线对象。
- `pins`：组件逻辑端口和拓扑节点名。
- `deleteEdges()`：根据拓扑把 edge 转换为 pin 名称连接，然后删除 edge；它不是通用元件删除。

初始化后优先读取：

```python
component.pins
component.args
```

不要自行假设 pin 数量、编号或节点名称。
