# 元件与参数

先在工作模型上找对象。把工程称呼映射到定义 RID 或已知标签。SDK 的标签与定义筛选使用精确匹配；可以先列候选再查接线。不要求工程师预先知道实例 ID。

```python
from auto_modeling.diagram_batch import find_diagram_components
from auto_modeling.component_args import get_diagram_components

# 不传过滤条件可列出全部候选；各过滤器接受列表。
matches = find_diagram_components(model, canvases=[canvas_key], definitions=[definition_rid])
cell = get_diagram_components(model, [selected_id])[0]
```

**查一个值。** 读 `cell["args"]` 及对应元件定义的 `parameters[].items[]`。按字段 key 读取含义、类型、单位和启用条件。实例省略或取空值时核对定义默认值；表达式同时保留源文本。遇到 `$变量名`，核对当前参数方案及画布变量的作用域；复杂表达式的有效值不能可靠求出时，返回原式和缺失依据。额定有功、控制给定、潮流结果要按用户问的量分别取证。

**改实例。** 将给定值换算到定义单位，按定义检查启用条件、上下界及区间开闭。实例引用共享变量时，改成常量会解除该实例在各方案中的绑定。若用户的目标可能是调整整个工况，先说明两种作用范围。相同有效值且用户只要求调整数值时，保留原存储形式。

```python
from stage_parameter_edits import stage_parameter_edits

candidate, receipt = stage_parameter_edits(
    model, [{"cell": selected_id, "field": field_key, "value": new_value}],
    definition_resolver=resolve,
)
if candidate is not None:
    readback = get_diagram_components(candidate, [selected_id])[0]["args"]
```

在更新前记录原字段和模型状态。核对回读值、目标外的字段和方案，确认差异符合请求后再令 `model = candidate`。SDK 写接口处理字段类型，工程范围和表达式含义仍需根据定义核对。

同一组修改可在 `patches` 列表传入多项。`stage_parameter_edits` 位于本 Skill 的 `scripts/` 下。收到 `PARAMETER_EDIT_REJECTED` 时，根据回执中的 `cell`、`field` 和 `message` 说明问题，保留当前工作模型。

**解析定义。** 云端可用 `auto_modeling.component_model.get_component_model` 作为 `resolve`。若已有按定义 RID 索引的缓存，用本地解析函数供写接口和接线接口共用，缺项时指出缺少哪个 RID：

```python
def resolve(rid):
    entry = definitions[rid]
    return {"name": entry.get("name", rid), **entry.get("revision", entry)}
```

**改参数方案。** 用 `auto_modeling.configs.list_configs(model)` 列方案，`get_config(model, index)` 读所选方案；字段定义在模型的 `revision.parameters`。修改共享字段前，查看哪些元件参数、表达式或画布变量引用它。列出已确认的使用者，说明未能解析的引用。作用域明确后在副本上调用 `update_config(candidate, index, {key: value})` 并再次 `get_config` 读回。
