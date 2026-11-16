# WS_GuangMnag — 面向视障人士的云端协同视觉导航系统

> 论文配套代码与实验数据仓库
>
> **论文题目**：面向视障人士的云端协同视觉导航系统：NoMaD 拓扑导航与 YOSO 语义避障的双通道融合
>
> **作者**：钟浩天（西南石油大学 理学院）
>
> **联系**：202431094310@stu.swpu.edu.cn

---

## 这个仓库是什么

一套为视障人士提供**室内无 GPS 场景连续目标引导**的完整系统，以及支撑论文全部实验结论的可复现代码与数据。

**核心思路**：手机只负责采集图像、语音交互和安全仲裁；重计算全部卸载到云端 GPU。云端并行运行两条推理通道——NoMaD 扩散策略做拓扑图导航，YOSO 全景分割做语义避障；手机端用一个**四规则安全仲裁器**解决"两个模型给出冲突建议"和"模型输出抖动"这两个助盲场景特有的问题。

**为什么不用端侧推理**：同一模型在 Jetson Orin Nano（15 W）上端到端需 394.1 ms，已占导航帧间隔（700 ms）的 56%；云端 RTX 4090 只需 103.7 ms，仅占 15%，保留 6.7 倍余量。这是本系统选择服务级卸载的直接依据（详见论文 §5.5）。

---

## 目录结构

```
WS_GuangMnag/
├── README.md                      本文件
├── LICENSE                        开源协议
│
├── android-app/                   Android 客户端（Kotlin + Jetpack Compose）
│   └── app/src/main/java/com/wsplus/guide/
│       ├── MainActivity.kt                    主入口与导航
│       ├── CloudTopologyNavigationScreen.kt   拓扑导航界面 + 四规则仲裁器
│       ├── TopologyMapRecordingScreen.kt      拓扑图录制（相机 + IMU 同步采集）
│       ├── TopologyMapsScreen.kt              地图管理与云端同步
│       ├── ArbitrationLogger.kt               仲裁事件记录（实验用）
│       ├── NavigationRouteVisualization.kt    路线进度可视化
│       ├── VisionFeatureScreen.kt             避障 / 寻物 / 环境描述
│       └── VoiceControl.kt                    语音交互
│
├── cloud-service/                 云端服务（Python + FastAPI）
│   ├── app.py                     HTTP 服务与路由
│   ├── inference.py               NoMaD 推理后端（含节点张量缓存优化）
│   ├── yoso_service.py            YOSO 侧车服务（127.0.0.1:8001）
│   ├── run-gpu.sh                 一键启动脚本
│   └── requirements-gpu.txt       依赖清单
│
├── experiments/                   论文实验脚本（全部可复现）
│   ├── exp_latency.py             E1 推理时延测量
│   ├── exp_navigation_replay.py   E2 导航成功率与节点跟踪
│   ├── exp_e3_eval.py             E3 避障准确率
│   ├── exp_arbitration.py         E4 仲裁器消融（6 种规则组合）
│   ├── exp_arbitration_rules234.py E4 真机验证（规则 2/3/4）
│   ├── exp_cross_session.py       E6 跨会话泛化
│   ├── benchmark_edge.py          边缘设备时延基准
│   ├── verify_cache_equivalence.py 缓存优化精度等价性验证
│   ├── exp_blur_vs_unknown.py     模糊度与 unknown 输出的关联分析
│   ├── exp_inter_annotator_v2.py  标注一致性（Cohen/Fleiss κ）
│   └── ...                        共 40 个脚本
│
├── data/                          实验数据
│   ├── labels/                    E3 标注（作者标注 + 4 位盲标者独立标注）
│   ├── results/                   全部实验结果 JSON（70 个文件）
│   ├── routes/                    13 条自采路线的节点图像与 IMU 数据
│   └── topomaps/                  拓扑图示例
│
├── figures/                       论文全部 9 张图的生成脚本与成品
│   ├── fig1_architecture.png
│   ├── fig2_arbitration.png
│   ├── fig3_latency.png
│   ├── fig4_confusion.png
│   ├── fig5_per_class.png
│   ├── fig6_baseline.png
│   ├── fig7_edge_vs_cloud.png
│   ├── fig8_cross_session.png
│   └── fig9_arbitration234.png
│
└── paper/                         论文源文件
    ├── 论文正文.md
    └── 论文正文（期刊格式）.docx
```

---

## 快速开始

### 1. 云端服务

```bash
cd cloud-service

# 安装依赖（需要 CUDA 环境）
pip install -r requirements-gpu.txt

# 准备模型权重
#   NoMaD: model_weights/nomad.pth
#   YOSO:  /root/ws/modle1/yoso_res50_coco (1).pth

# 一键启动（导航服务 :6006 + YOSO 侧车 :8001）
bash run-gpu.sh
```

验证服务：

```bash
curl http://127.0.0.1:6006/health
# {"status":"ok","inference_ready":true,"yoso":{"status":"ok",...}}
```

### 2. Android 客户端

```bash
cd android-app

# 需要 JDK 17 与 Android SDK
export JAVA_HOME=/path/to/jdk-17
./gradlew :app:assembleDebug
```

安装后，在 App 的「拓扑图导航」页面把服务地址设为你的云端地址。

### 3. 复现论文实验

```bash
cd experiments

# E1 推理时延（需云端服务运行）
python exp_latency.py \
    --service http://127.0.0.1:6006 \
    --map-id <你的地图 ID> \
    --dest <目标节点名，如 66.jpg> \
    --frames 60 \
    --out ../data/results/latency_rerun.json

# E4 仲裁器消融（纯离线，不需要服务）
python exp_arbitration.py --trace ../data/results/trace_real.json \
    --out ../data/results/arbitration_rerun.json

# 缓存优化精度等价性（需 GPU）
python verify_cache_equivalence.py

# 标注一致性（无参数，直接运行；读取 data/labels/ 下的标注文件）
python exp_inter_annotator_v2.py
```

---

## 关键设计：四规则安全仲裁器

这是本系统最核心的机制，用于在**不修改模型输出**的前提下抑制误报与抖动。

| 规则 | 触发条件 | 行为 |
|---|---|---|
| **规则 1** 方向确认 | 同一方向连续 2 帧 | 才播报，抑制单帧抖动 |
| **规则 2** 冲突复核 | 导航与避障方向不同且连续 2 帧 | 以视觉避障为准，播报"方向受阻"并让行 |
| **规则 3** 保持窗口 | 告警触发后 5 s | 抑制导航播报，给用户反应时间 |
| **规则 4** 超时降级 | 请求超时 >7 s 或 unknown 连续 2 帧 | 播报"请停下确认"，安全侧失败 |

**参数**（见 `CloudTopologyNavigationScreen.kt`，可依用户反应速度调整）：

```kotlin
NAV_DIRECTION_CONFIRMATIONS = 2      // 导航方向确认帧数
OBSTACLE_STATE_CONFIRMATIONS = 2     // 避障状态确认帧数
GUIDANCE_HOLD_MS = 5000              // 保持窗口 5 秒
OBSTACLE_RESPONSE_DEADLINE_MS = 7000 // 超时降级 7 秒
OBSTACLE_ALERT_REPEAT_MS = 5000      // 告警重复间隔
```

**真机验证结果**（3 段障碍录制，576 s / 712 帧）：

- 规则 2 冲突让行触发 **37 次**
- 规则 3 保持窗口合规率 **97.3%**（让行后导航静默中位数 9.4 s）
- 规则 4 降级触发 **3 次**
- 离线消融：播报降低 21%、方向抖动降低 51%

---

## 主要实验结论

| 实验 | 指标 | 数值 |
|---|---|---|
| **E1** 推理时延 | NoMaD P50 / YOSO P50 | 103.7 ms / 49.7 ms（RTX 4090） |
| **E2** 导航成功率 | 到达率 / 节点跟踪准确率 | 100%（9 条路线）/ 95.4% |
| **E3** 避障准确率 | 方向准确率 / 楼梯召回率 | 87.4%（盲标复核修正后）/ 100% |
| **E4** 仲裁器 | 播报变化 / 抖动变化 | −21% / −51% |
| **E5** 边缘 vs 云端 | Jetson P50 / 比值 | 394.1 ms / 3.80× |
| **E6** 跨会话失锁修复 | 误差均值 / P90 | −60.7% / −57.1% |

### 关于 E3 的数字：一次自我修正

初版标注由作者在 YOSO 预标注基础上修正，报告准确率 97.7%。后续邀请 4 位不了解本项目的标注者独立**盲标**（只看图像，不看任何模型输出），发现：

- 作者标注与 YOSO 一致率 97.7%，而盲标多数投票与 YOSO 仅 70.1%
- 26 个"YOSO 与盲标多数不一致"的样本中，作者只修正了 2 个（7.7%）
- 作者重新独立复核后，9 个明确判断与盲标者 **100% 一致**

**结论：初版标注存在锚定偏差。修正后准确率为 87.4%（**降低 10.3 个百分点**）**，论文以此为准并撤回了 97.7%。详见论文 §5.3.2。

### 一个意外的发现

论文还报告了 YOSO 输出"不确定"与图像模糊的显著关联：unknown 组样本的边缘强度（Tenengrad）仅为正常样本的 **34%**（p = 0.0037），高频能量为 77%（p = 0.0107），而**亮度无差异**（p = 0.729）。这说明失效主因是对焦/运动模糊，而非光照不足——对实际部署有直接指导意义。

---

## 数据说明

### 自采路线（13 条）

| 路线 | 节点数 | 说明 |
|---|---|---|
| `1`, `2-2` | 32 | 基础路线 |
| `1-2`, `2-6` | 74, 67 | 长路线 |
| `1-3`, `2-7` | 55, 52 | 含转弯 |
| `2-8`, `左右-2` | 31, 36 | 转弯场景 |
| `室内`, `室内-3` | 13, 15 | 短路线 |
| `花园`, `花园-3` | 98, 83 | 视觉重复场景（仅定性） |
| `2-7-3` | 88 | 跨会话实验用（不同光照重录） |

每条路线包含节点图像（`0.jpg`–`N.jpg`）与 `imu.csv`（50 Hz 陀螺仪/加速度计/旋转矢量）。

### 遗留数据集声明

论文 §5.1 的 A 层分析使用了团队早期边缘部署阶段遗留的数据集（121 条轨迹、3 432 帧）。**该数据非本文作者采集**，论文已明确声明。本仓库不包含该数据集；相关分析的原始结果在 `data/results/offline_analysis.json`。

### 标注数据

`data/labels/` 包含：

- `labels_filled.json` — 作者标注（87 张，含 YOSO 预标注字段）
- `A+.json` / `B+.json` / `C+.json` / `D+.json` — 4 位盲标者独立标注（v2 协议）
- `blind_label_v2.html` — 盲标工具（单文件，双击即可用）

**盲标协议**：标注界面仅显示图像本身，不提供模型预测或先验标注。任务定义为"假想朝画面中心行走，下一步往哪走"，明确规定"正前方畅通则选向前，只有受阻才选左右"——这个定义是为了消除 v1 协议中"哪里能走"的歧义（v1 的 Fleiss' κ 仅 0.375，v2 提升至 0.508）。

---

## 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.8+ | 云端服务 |
| PyTorch | 1.10.1+ | NoMaD 推理 |
| diffusers | 0.11.1 | 扩散调度器 |
| Detectron2 | — | YOSO 运行时 |
| CUDA | 11.3+ | GPU 推理 |
| Android SDK | API 30+ | 客户端 |
| JDK | 17 | Android 构建 |

**已验证平台**：

- 云端：RTX 4090（24 GB）/ RTX 4080 SUPER，Ubuntu 20.04
- 边缘：Jetson Orin Nano 15 W，L4T R35.6.3（注意：**RTX 5090 不兼容** torch 1.10.1，因算力 12.0 超出 CUDA 11.3 支持范围）

---

## 已知限制

1. **拓扑图导航假设环境与录制时一致**，环境改变（挪动货架）需重录，目前无增量更新机制。
2. **YOSO 输出语义方向但不输出距离**，避障建议是"方位级"而非"米级"，必须依赖盲杖补充近距探测。
3. **云端集中推理存在单点故障与隐私风险**（图像上传）。当前以 Bearer Token + HTTPS 缓解，图像不做存储（帧处理后即释放）；端到端加密与端侧轻量化蒸馏是后续方向。
4. **C 层人因实验尚未开展**——本文尚未经真实视障用户的长期使用验证。当前正在设计蒙眼健视者预实验。
5. **E3 的"可通行方向"任务存在固有主观性**（4 位盲标者 Fleiss' κ = 0.508），87.4% 的准确率应在此前提下解读。

---

## 引用

如果本仓库对你的工作有帮助，请引用：

```bibtex
@article{zhong2026wsplus,
  title   = {面向视障人士的云端协同视觉导航系统：NoMaD 拓扑导航与 YOSO 语义避障的双通道融合},
  author  = {钟浩天},
  journal = {（期刊名待定）},
  year    = {2026}
}
```

**依赖的核心模型**，请一并引用其原始论文：

- **NoMaD**: Sridhar A, Shah D, Glossop C, et al. NoMaD: Goal Masked Diffusion Policies for Navigation and Exploration. arXiv:2310.07896, 2023.
- **YOSO**: Hu J, Huang L, Ren T, et al. You Only Segment Once: Towards Real-time Panoptic Segmentation. CVPR 2023: 17775-17784.
- **ViNT**: Shah D, Sridhar A, Dashora N, et al. ViNT: A Foundation Model for Visual Navigation. CoRL 2023.
- **GNM**: Shah D, Sridhar A, Bhorkar A, et al. GNM: A General Navigation Model to Drive Any Robot. ICRA 2023: 7166-7173.

---

## 免责声明

**本系统是科研原型，不是医疗设备或辅助器具产品，不可用于实际出行导航。**

避障为视觉辅助，**不能测距、不能替代盲杖**。提示冲突、不确定或服务中断时，用户必须停下确认并依靠盲杖与自身判断。任何情况下都不应将本系统的输出作为唯一安全依据。

---

## 许可

代码采用 MIT 许可证，见 [LICENSE](LICENSE)。

数据与论文文本采用 CC BY 4.0。
