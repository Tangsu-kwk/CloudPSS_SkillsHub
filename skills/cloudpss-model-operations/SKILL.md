---
name: cloudpss-model-operations
version: 1.0.0
description: 查询和编辑 CloudPSS 模型。当用户需要查看模型中的元件、接线或参数，或要求在模型上增删元件、调整接线、修改元件参数或参数方案时使用。
---

# CloudPSS 模型操作

从本包加载 SDK。在本轮的 Python 执行环境中，以本 Skill 根目录为工作目录执行下列代码，然后在同一解释器内调用 SDK。

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from sdk_bootstrap import activate
activate()
```

**确定工作模型。** 优先沿用当前会话持有的 SDK `Model`。「刚才那只」「改完后」指向同一工作副本及已定位的实例。首次打开已知项目 RID 时调用 `auto_modeling.project_session.open_project(rid)`；已有本地模型文档时，用 `auto_modeling.diagram_aux.model_from_document(document)` 载入。若执行环境已释放未保存副本，说明状态已丢失，重新确定起点。运行依赖或鉴权问题见[运行环境](references/runtime.md)。

按本轮动作读取对应指引：

- **查询或改参**：按画布、定义和标签定位实例；标签重名时用相邻元件、端口或已知参数辨认。读实际字段和定义，说明单位、值的来源及修改作用域。[元件与参数](references/parameters.md)
- **添加、删除或改接**：确认目标画布、元件定义、实例 ID 和实际端口 key。删除前核对随目标一起移除的边，改接后回读两个端点。[元件与接线](references/diagram.md)

**交付改动。** 在当前模型的独立副本上执行写操作，核对请求涉及的字段和连线后，将该副本作为会话的当前模型；失败时保留上一个副本。向用户报告实际对象和变化。用户只要求修改时保留内存版本；用户要求保存到指定项目时，调用 `auto_modeling.project_persistence.save_project(model, rid)`，核对回执并读回目标。是否提交计算由本次请求决定。
