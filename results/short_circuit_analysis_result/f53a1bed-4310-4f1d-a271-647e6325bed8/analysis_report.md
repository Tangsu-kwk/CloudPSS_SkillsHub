# 短路电流分析报告

## 分析对象

- 模型：`model/Makinohara_Shoko/test1-autotest`
- CloudPSS 仿真任务：`f53a1bed-4310-4f1d-a271-647e6325bed8`
- 目标故障：`canvas_0_965`
- 故障母线：`bus16`
- 基准线电压：500 kV
- 分析电流统一单位：`kA`

## 汇总结论

- 分析通道数量：3
- 最大峰值电流：19.9767 kA
- 最大故障 RMS 电流：9.05615 kA
- 最大稳态故障 RMS 电流：8.92789 kA
- 最大短路容量：7842.85 MVA
- 最小 SCR：n/a
- 最小 ESCR：n/a
- 最弱电网等级：`not_assessed`

## 通道指标

| 通道 | 原始单位 | 单位依据 | 峰值 (kA) | 故障 RMS (kA) | 稳态故障 RMS (kA) | 短路容量 (MVA) | SCR | ESCR |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| #example:0 | kA | parameter.name | 12.2813 | 7.75177 | 7.9019 | 6713.23 | n/a | n/a |
| #example:1 | kA | parameter.name | 19.9767 | 9.05615 | 8.92789 | 7842.85 | n/a | n/a |
| #example:2 | kA | parameter.name | 19.4375 | 8.78925 | 8.65297 | 7611.72 | n/a | n/a |

## Thevenin Equivalent and SCR

- 最小戴维南标幺阻抗、SCR 和 ESCR 以各通道计算结果及 `summary.csv` 为准。
- 当前最弱电网等级：`not_assessed`。

## 方法与限制

- 真实电流通道的原始单位由其 CloudPSS 元件定义参数元数据确认，并在计算前换算为 kA。
- `waveform.csv` 保存参与分析的标准化电流；`raw_waveforms/` 保存 CloudPSS 原始数值。
- 短路容量采用三相近似 `Ssc = √3 × Vll(kV) × I(kA)`。
- SCR/ESCR 与戴维南等值属于工程初筛，不替代设备校核级短路计算和并网专题研究。
- 完整逐点波形不写入本报告，避免把大量时序数据加载到智能体上下文。
