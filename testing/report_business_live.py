"""Build evidence report from one business run; never infer PASS from prose."""
import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
lines=['# 辅助建模业务任务测试记录','',
       '宿主：SCAgent2/newagentv2.py；真实 LLM：deepseek/deepseek-chat。该名称不能等同于尚未确认配置的部署端 DeepSeek V4 Flash。',
       '自动加载辅助建模、短路分析、报告三个 Skill；不调用报告生成 Skill。专业代码和宿主保持原样，测试器仅发送自然语言、观察与核验模型。',
       '云端只允许创建本轮指定新 RID；每个修改版和删除版单独保存并完整回读 implements、parameters、pins、configs、jobs。',
       '所有原模型 cells 每轮比对；每个任务结束独立 fetch 原模型。配置、元件 schema 缺少的物理含义不因拓扑刷新成功而认定正确。','',
       '## 任务状态','',
       '| 任务 | 新增 | 修改 | 删除 | 拓扑 | 云端版本数 | 总体状态 |',
       '|---|---|---|---|---|---|---|']
for out in sorted(root.iterdir()):
    if not out.is_dir(): continue
    result=read(out/'result.json') if (out/'result.json').exists() else {'task':out.name,'status':'running'}
    turns=read(out/'turns.json') if (out/'turns.json').exists() else []
    def r(k):return result.get(k,'未验证')
    lines.append(f"| {result['task']} | {r('create')} | {r('update')} | {r('delete')} | {r('topology')} | {len(result.get('cloud_saves',[]))} | {result['status']} |")
    detail=['# '+result['task'],'','## 机器核验结论','', '```json',json.dumps(result,ensure_ascii=False,indent=2),'```','','## 完整用户式对话与调试','']
    for i,t in enumerate(turns,1):
        detail += [f'### 第 {i} 轮：{t["phase"]}','','用户：','',t['user'],'','智能体：','',t['assistant'],'']
    detail+=['## 原始证据','',
             '- events.jsonl：完整工具请求、响应及消息；凭据替换为 REDACTED。',
             '- model-NN.json / previews-NN.json / topology-NN.json：逐轮模型、待确认计划和已有拓扑。',
             '- create-attempts.json / create-response-N.json：外部保存尝试与响应，失败不自动重试。',
             '- edited-cloud.json / deleted-cloud.json：独立新 RID 回读。',
             '- source-before.json / source-after.json：原模型比对。','']
    (out/'TEST_REPORT.md').write_text('\n'.join(detail),encoding='utf-8')
lines+=['','## 阅读边界','',
        '- 任务失败按具体阶段记录；运行时错误、模型澄清、测试断言和服务故障分开分析，不按条目数量算通过。',
        '- 结构成功不等于正确的端子语义；拓扑刷新也不等于 EMT 成功或物理结果合理。',
        '- 变压器、故障等需要端子含义的任务可能因 schema 缺失受阻；不得猜端子后计通过。',
        '- 模板枚举并非本轮目标；以组合业务需求为主要验收单位。',
        '- 本轮结果不能替代所有元件、参数范围、边界条件或仿真场景覆盖。','',
        '## 逐任务详录','']
for out in sorted(root.iterdir()):
    if out.is_dir():lines.append(f'- [{out.name}]({out.name}/TEST_REPORT.md)')
(root/'TEST_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(root/'TEST_REPORT.md')
