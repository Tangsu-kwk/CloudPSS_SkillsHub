# 元件与接线

下列动作在当前工作模型的独立副本 `candidate` 上执行。通过 `auto_modeling.diagram_reads.list_diagram_canvases(model)` 读取实际画布 key。参数 `resolve` 为定义查询函数，离线缓存的适配方法见[元件与参数](parameters.md)。

| 动作 | SDK 入口与核对依据 |
|---|---|
| 查看某实例的接线 | `diagram_batch.find_diagram_edges(model, terminals=[{"cell": cid}])` 返回显式边；按端口查询可再传 `port`。沿边读取另一端的实例、端口及定义。遇到命名连接时同时核对两端的 `pins`、信号类型及其作用域。 |
| 添加元件 | `diagram_edit.add_diagram_component(candidate, rid, position, canvas, args, pins, definition_resolver=resolve)`。位置形如 `{"x": x, "y": y}`。记录返回的实例 ID，读回定义、画布和参数。 |
| 连接两个端口 | `diagram_edit.add_diagram_edge(candidate, source, target, definition_resolver=resolve)`。端点形如 `{"cell": cid, "port": pin_key}`。核对定义中的电气或信号类型、方向和维度；动态生成的端口按当前实例参数确认，用 `add_dynamic_diagram_edge`。 |
| 改接已有边 | 先用 `diagram_edit.get_diagram_edges(model, [edge_id])` 读取原始两端。核对新端口后调用 `diagram_batch.update_diagram_edges(candidate, [edge_id], target=new_terminal, definition_resolver=resolve)`；改源端时传 `source`。读回改动端和保留端。 |
| 删除元件或边 | `diagram_edit.delete_diagram_cells(candidate, [cid])` 会递归删除指向被删对象的关联边。查看回执，复查被删对象、受影响端点及保留支路。仅断开一根线时传该边 ID。若连接由命名引脚建立，应定位并修改相应绑定。 |

以上模块均位于 `auto_modeling`。一次添加并接线可在同一副本连续完成，用实际返回的 ID 组装后续调用。只在这些动作和回读都成功后接纳该副本。
