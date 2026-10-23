# 仓库内容清单

本文件由构建脚本自动生成。**合计 602 个文件，25.5 MB**（低于 GitHub 100 MB 建议上限）。

## 目录结构

| 目录 | 文件数 | 体积 | 内容 |
|---|---|---|---|
| `android-app/` | 3 | 0.00 MB | Android 客户端源码（Kotlin + Compose） |
| `cloud-service/` | 11 | 0.05 MB | 云端服务（FastAPI + NoMaD 推理 + YOSO 侧车） |
| `data/labels/` | 14 | 5.13 MB | E3 标注（作者 + 4 位盲标者）+ 标注图片 + 盲标工具 |
| `data/labels/images_e3/` | 87 | 3.61 MB |  |
| `data/results/` | 70 | 0.62 MB | 实验结果 JSON（含仲裁日志 CSV） |
| `data/results/arb_logs/` | 10 | 0.09 MB |  |
| `data/routes/1/` | 33 | 2.19 MB |  |
| `data/routes/2-6/` | 68 | 2.77 MB |  |
| `data/routes/2-7/` | 53 | 2.53 MB |  |
| `data/routes/2-7-3/` | 89 | 3.70 MB |  |
| `data/routes/左右-2/` | 37 | 1.50 MB |  |
| `experiments/` | 41 | 0.33 MB | 论文全部实验脚本（40 个 .py） |
| `experiments.bak/` | 41 | 0.32 MB |  |
| `experiments.bak/traces/` | 1 | 0.00 MB |  |
| `figures/` | 9 | 1.05 MB | 论文 9 张图成品 |
| `paper/` | 2 | 1.38 MB | 论文 md 源文件与 docx |
| *(data 合计)* | 461 | 22.14 MB | 全部实验数据 |
| 根目录 | 4 | 0.02 MB | README / LICENSE / MANIFEST / .gitignore |

**合计：602 个文件，25.5 MB**

## 复现验证状态

以下脚本已在仓库结构下实际运行通过，输出与论文数值一致：

| 脚本 | 复现结果 | 论文位置 |
|---|---|---|
| `exp_arbitration.py --trace data/results/trace_real.json` | 完整版播报 7 次 / 方向变化 2 次 | 表 6 |
| `exp_arbitration_rules234.py` | 规则 2 触发 37 次 / 规则 3 合规 97.3% / 规则 4 触发 3 次 | 表 7 |
| `exp_blur_vs_unknown.py` | Tenengrad 0.34× (p=0.0037) / 高频能量 0.77× (p=0.0107) | 表 6（§5.3.2） |
| `exp_e3_stratified_v2.py` | L1 全体一致 36 张 100% / L3 多数 31 张 96.8% | §5.3.2 |
| `exp_inter_annotator_v2.py` | 方向 Fleiss κ = 0.508 / v1 κ = 0.530 | §5.3.2 |

## 未包含的内容及原因

| 内容 | 体积/数量 | 原因 |
|---|---|---|
| 模型权重 | `nomad.pth` 73 MB、`yoso_res50_coco.pth` 482 MB | 体积过大；按 README「快速开始」从原项目获取，或联系作者 |
| 遗留数据集 | 121 条轨迹、3 432 帧 | 非本文作者采集，版权归属团队早期项目，不宜转授 |
| 其余 8 条路线图像 | — | 控制体积；已保留 5 条代表性路线（覆盖短/长/转弯/跨会话），其余可按需提供 |
| 标注工具历史版本 | 86 MB | 仅保留最终盲标工具 `blind_label_v2.html` |
| 第三方工具 | — | 非本项目代码（scrcpy 等） |

## 关键数值 → 脚本 → 结果文件 对照

| 论文数值 | 产出脚本 | 结果文件 |
|---|---|---|
| NoMaD P50 = 103.7 ms | `exp_latency.py` | `data/results/latency.json` |
| 到达率 100% / 跟踪 95.4% | `exp_navigation_replay.py` | `data/results/navigation_all.json` |
| 方向准确率 87.4%（修正后） | `exp_e3_eval.py` + `exp_e3_revised.py` | `data/results/e3_revised.json` |
| 规则 2 触发 37 次 | `exp_arbitration_rules234.py` | `data/results/arbitration_rules234.json` |
| 边缘 394.1 ms / 3.80× | `benchmark_edge.py` + `bench_cache_impact.py` | `data/results/edge_vs_cloud.json` |
| 失锁修复 −60.7% / −57.1% | `exp_cross_session.py` | `data/results/cross_session_summary.json` |
| Fleiss κ = 0.508 | `exp_inter_annotator_v2.py` | `data/results/inter_annotator_v2.json` |
| 模糊 p = 0.0037 | `exp_blur_vs_unknown.py` | `data/results/blur_vs_unknown.json` |
| 缓存等价性 torch.equal = True | `verify_cache_equivalence.py` | `data/results/cache_bench.json` |

## 关于 E3 数字的说明

论文 §5.3.2 报告的方向准确率 **87.4%** 是**盲标复核修正后**的值。初版基于作者在 YOSO 预标注基础上修正的标注，报 97.7%，后经 4 位独立盲标者验证发现锚定偏差（作者与 YOSO 一致率 97.7%，盲标多数仅 70.1%；26 个分歧样本中作者仅修正 2 个），故撤回 97.7% 并以 87.4% 为准。相关验证脚本与数据均在本仓库：

- `experiments/diag_anchor_bias.py` — 锚定效应诊断
- `experiments/verify_anchor.py` — 统计检验
- `experiments/exp_e3_revised.py` — 修正后重算
- `data/labels/A+.json` … `D+.json` — 4 位盲标者原始标注

## 若需完整数据

请联系 **202431094310@stu.swpu.edu.cn**，说明用途后可获取完整路线图像与模型权重。
