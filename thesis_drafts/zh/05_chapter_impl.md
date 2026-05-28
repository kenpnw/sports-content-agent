# 第 4 章 关键技术实现

本章给出系统中六个关键模块的具体实现细节：4.1 节 NBA Live API 接入；4.2 节视频时间映射；4.3 节记分牌可见性检测；4.4 节战术片段对齐与提取；4.5 节战术解说生成；4.6 节多平台社交内容打包；4.7 节网页评审界面。

## 4.1 NBA Live API 接入与 Play-by-Play 解析

### 4.1.1 接入挑战

NBA 官方提供的 Live API（https://cdn.nba.com/static/json/liveData/...）虽公开但缺乏正式文档，且对请求头敏感——使用默认的 Python `requests` 默认 User-Agent 会被服务端以 HTTP 403 Forbidden 拒绝。本研究通过两步骤解决：

1. **浏览器级请求头模拟**：将 User-Agent 设置为 Chrome 浏览器的标准字符串，并附上 `Referer: https://www.nba.com/`、`Accept-Language: en-US`、`Accept: application/json` 等头部，模拟浏览器环境；
2. **多 endpoint 备份**：除了 `playbyplay/playbyplay_<game_id>.json` 主端点，备用调用 `boxscore/boxscore_<game_id>.json` 作为校验，避免单一端点失效导致整体失败。

### 4.1.2 比赛选择

本系统支持两种比赛选择路径：

- **当日比赛**：调用 `scoreboard/todaysScoreboard_00.json` 端点获取当日所有比赛；
- **近 N 天比赛**：调用 `scheduleLeagueV2_1.json` 端点获取整个赛季的赛程数据，过滤出最近 N 天（默认 30 天）的已完赛事件。本研究在 Webapp 控制台暴露了"刷新近 30 天"按钮，让用户在演示场景下临时挑选任意一场近期比赛。

### 4.1.3 Play-by-Play 解析

NBA Live API 返回的 PBP 数据是一个嵌套 JSON 结构，每个事件包含约 30 个字段。本研究的 `nba_pbp_fetcher` 模块将其规范化为内部使用的 `replay_event` 数据结构，关键字段包括：

- `period`（节次：1-4 或 5+ 加时）
- `clock`（剩余比赛时钟，ISO 8601 duration 格式如 `PT10M51.00S`）
- `action_type`（动作类型：2pt / 3pt / freethrow / rebound / turnover / steal / block / foul 等）
- `description`（人类可读描述如 `"L. James 26' 3PT running pullup (5 PTS)"`）
- `player_id` / `team_id`
- `score_home` / `score_away`

### 4.1.4 观察构建

`possession_boundary_detector` 模块从规范化后的事件序列中识别"回合边界"，并按规则筛选出"具有内容价值的回合"：

- 任何得分回合（made_shot）
- 关键失误（turnover with high impact）
- 防守端关键事件（block、steal）
- 终结时刻（最后 2 分钟的关键回合）

在 OKC vs LAL G1 上，规则引擎从原始的 500-700 个 PBP 事件中筛选出约 60 个 observation，覆盖了一节比赛的战术执行样本（而非单纯的高光集锦）。

## 4.2 视频时间映射（Video Time Mapping）

### 4.2.1 OCR 帧采样策略

视频时间映射的目标是建立"视频秒数 ↔ 比赛时钟"的映射函数。该映射的构建依赖对视频每秒一帧的采样与 OCR。本研究在采样实现上对比了两种方案：

- **方案 A：OpenCV 随机定位**。使用 `cv2.VideoCapture` 的 `cap.set(cv2.CAP_PROP_POS_FRAMES, k)` 随机定位到第 k 秒帧。该方案在 MP4 上速度尚可，但在 MKV 格式上由于关键帧间隔大导致 seek 极慢（每次 seek 需要数百毫秒）。
- **方案 B：ffmpeg 流水线管道**。使用 `ffmpeg -i video.mkv -vf fps=1 -f image2pipe -pix_fmt bgr24 -vcodec rawvideo -` 将视频按 1fps 解码后通过管道流式传输到 Python 进程，由 OpenCV 直接 `np.frombuffer` 解析。

实测在 7.5GB 的 OKC vs LAL G1 MKV 视频上：方案 A 单次随机定位约 400-800 毫秒，9000 秒共耗时约 1.5-2 小时；方案 B 流水线方式仅耗时约 8-10 分钟，速度提升约 12-15 倍。本研究采用方案 B 作为生产方案。

### 4.2.2 OCR 实现

每帧的记分牌区域（ROI）由用户预先标定（坐标存于 `<video>.scoreboard_roi.json`），通常位于画面底部 78%-97% 的水平条带内。对该 ROI 做 OCR：

- **OCR 引擎**：EasyOCR（基于深度学习的多语言 OCR 库），中英文混合识别能力较好；
- **预处理**：先对 ROI 做灰度化 + 自适应阈值化，提升记分牌数字的对比度；
- **后处理**：用正则表达式从 OCR 输出中抽取出"`<节次> <比分主> <比分客> <时钟剩余>`"四个字段，过滤掉显然不可能的值（如时钟显示 99:99）。

成功识别的样本约占总采样数的 60-70%（其余对应于记分牌不可见或被遮挡的瞬间）。在 OKC vs LAL G1 上从 9000 个采样中得到约 95 个有效样本，分布于 4 个节次。

### 4.2.3 分段线性插值

在 4 个节次内分别构建"视频秒数 ↔ 比赛剩余时钟"的分段线性映射：

```python
def video_seconds_for(period, target_clock_seconds):
    samples = ocr_samples_for_period(period)
    samples.sort(key=lambda s: s.clock_remaining_seconds)
    # Find the two samples bracketing target_clock_seconds
    # and do linear interpolation between their video_seconds.
    ...
```

实践中遇到的关键 bug 与修复：

- **早期 bug**：早期版本未对每节单独处理，导致 Q1 的样本和 Q2 的样本被串联线性拟合，结果是节末附近的事件出现 1000+ 秒的对齐错误；
- **修复**：在 `_apply_time_map` 函数中先按 period 分组，再按 period 各自做线性插值。修复后误差从 1000+ 秒降至 30 秒以内（OCR 样本覆盖范围内）。

## 4.3 记分牌可见性检测（Scoreboard Visibility Detection）

### 4.3.1 设计思路

记分牌可见性检测的目标是判断视频每一秒是否处于"播放段"（记分牌可见 → 正在进行比赛）还是"非播放段"（记分牌不可见 → 回放、慢镜头、广告）。本研究采用 OpenCV 模板匹配技术，避免引入深度学习推理的部署成本。

### 4.3.2 模板抽取与匹配

- **模板抽取**：从 4 个节次的不同时刻（每节 3 个时间点）抽取记分牌 ROI 区域，共 12 个参考模板。覆盖了同一节内可能出现的轻微图形变化（如比分变化导致的数字位置变化、商业广告角标的出现/消失等）。
- **匹配算法**：对每秒采样帧的 ROI 与 12 个参考模板分别用 `cv2.matchTemplate(method=cv2.TM_CCOEFF_NORMED)` 计算归一化相关系数，取最大值作为该秒的可见性得分。
- **阈值与平滑**：经验阈值 0.65 区分可见 vs 不可见。原始信号会存在单帧噪声（如转场瞬间的误判），通过 3 秒窗口的中值滤波做平滑，得到最终的 `scoreboard_visibility_v2_smoothed.json`。

### 4.3.3 检测准确率的演进

本研究在系统迭代中对该检测器做了两个版本：

- **v1（单模板）**：每节仅抽取 1 个参考模板，全场仅 4 个。结果是非比赛画面（特别是教练特写、球员特写）也被高分匹配，导致播放段过度宽松——OKC vs LAL G1 上 87% 的视频时长被误标为播放段，比真实的 60% 偏高 27 个百分点。
- **v2（密集模板 + 比赛窗口过滤）**：每节抽 3 个模板（共 12 个），并加入"开场前 5 分钟 + 终场后 5 分钟必为非播放段"的硬规则。结果改善为 60% 播放段，与人工标注吻合。

最终采用 v2 方案。

## 4.4 战术片段对齐与提取

### 4.4.1 对齐策略

如第 3.2.2 节所述，每个 observation 经"OCR 时间映射"得到其在视频中的预期秒数后，需要进一步决定 clip 的具体时间窗口。本研究的对齐策略综合考虑三个因素：

- **事件位置归一化**：将事件设定为出现在 clip 的第 78% 位置（即事件后只留 22% 时长收尾），这一比例基于对人工编辑的 highlight 节奏的观察。
- **窗口长度自适应**：默认窗口 10 秒（事件前 8 秒铺垫，事件后 2 秒收尾），对快攻类回合可以延长到 12 秒，对罚球类回合可以缩短到 6 秒。
- **播放段 snap**：若初始窗口落在非播放段，按 3.2.2 节的 snap 策略移动到最近的播放段。

### 4.4.2 边界情况处理

实践中发现几个需要特殊处理的边界情况：

- **节末 / 比赛结束事件**：clock < 15 秒的事件可能没有 OCR 样本覆盖，对这类事件不强制 snap，使用最佳尝试线性外推，并在 clip 元数据中标记 `extrapolated=true`；
- **clip 时间窗口超出视频时长**：早期版本未做检查，导致部分 clip 文件大小为 0 字节。修复方法是在 ffmpeg 切取前先 clamp 窗口到 `[0, video_duration]`；
- **重复事件**：同一秒有多个 PBP 事件（如得分 + 助攻 + 命中三分的连续事件），合并为同一个 clip 避免内容重复。

### 4.4.3 ffmpeg 切取与 GIF 生成

确定 clip 时间窗口后，使用 ffmpeg 同时生成 MP4 视频片段与 GIF 动图：

```bash
# MP4 clip
ffmpeg -ss <start> -t <duration> -i <video> -c copy <output>.mp4

# GIF (用于网页展示，单 GIF 约 500KB-1MB)
ffmpeg -ss <start> -t <duration> -i <video> -vf "fps=10,scale=480:-1" <output>.gif
```

每个 clip 还会调用 `extract_clip_frames` 提取 6 张关键帧（均匀分布，偏向第二个 50% 区段），用于网页展示。

## 4.5 战术解说生成

### 4.5.1 4 段流水线

`tactic_analyzer.VideoScoutAnalyzer.analyze` 方法实现 5-Agent 协议的具体调用流程，分 4 个 LLM 调用阶段：

- **Stage 1（总览生成）**：基于 60 个 observation 的概览，生成报告的 title、executive_summary、tactical_themes 字段；
- **Stage 2（key_segments 生成）**：对每个 observation 调用 Writer 角色，生成 observation / decision_analysis / win_loss_impact 三段；这是耗时最长的阶段，60 个 segment 约 60-70 秒。
- **Stage 3（quarter_flow 与 deciding_factors）**：基于 Stage 2 的输出，生成各节比赛流向与决定胜负的因素分析；
- **Stage 4（content_angles 与 player_decision_notes）**：生成多平台内容建议与球员决策点评。

每个 Stage 内部都遵循"Prompt Contract 构造 → LLM 调用 → 输出解析 → Fact Checker 校验 → Risk Guard 校验"的标准流程。

### 4.5.2 篮球术语库的注入

Writer 角色的 system prompt 中显式注入了 30+ 篮球术语的中英对照表，例如：

```
- 一五挡拆 (1-5 PnR / High PnR)：1 号位与 5 号位的高位挡拆
- Spain PnR / 西班牙挡拆：3 人 PnR 战术，掩护者再被掩护
- Hammer 战术：弱侧底角设置掩护接突分
- 反跑 (Backdoor cut)：防守过度贴防时反向切入
- 牛角阵 (Horns set)：双高位策应起手式
... (共 30+ 条)
```

这一注入使 LLM 倾向于使用专业术语而非干瘪的"挡拆"、"配合"等通用词。

### 4.5.3 "不强行套战术名"负面规则

实际部署中发现 LLM 倾向于对每个回合都套用战术名（即使是失误、罚球、节末走时等非战术回合），导致解说显得幼稚。本研究在 prompt 中加入"严格禁止"规则：

```
**严格禁止以下情况强行套战术名**：
・所有失误（turnover/bad pass/lost ball/...）→ 写「失误回合，原因是 XX」，不写「属于 XX 战术」
・节末/比赛结束（period end / game end）→ 写「QN 收尾」或「全场结束」
・个人单打 ISO 中随意运球后强攻 → 这是个人能力不是战术
・抢板二次进攻 → 写「二次进攻」即可
・罚球 → 写「罚球时刻」
・无明显战术配合的过渡进攻、转换快攻 → 写「快攻 / Transition」即可
```

加入这一规则后，LLM 输出的战术名使用更克制、更专业。

### 4.5.4 LLM 调用工程细节

- **API 提供方**：DeepSeek（兼容 OpenAI SDK 接口）
- **模型选择**：`deepseek-chat`（适合多数任务）+ `deepseek-reasoner`（仅在 Stage 1 的综合分析时按需启用）
- **超参**：temperature=0.6（兼顾创造性与稳定性）、max_tokens=400/段、top_p=0.9
- **重试策略**：API 调用超时（默认 20s）或返回 5xx 自动重试 3 次；输出解析失败时重新生成（最多 2 次）；连续失败的回合 fallback 为模板填充。

## 4.6 多平台社交内容打包

`social_packager` 模块按第 3.7.2 节的策略，为四个平台生成差异化的内容包。每个平台的关键实现细节如下：

- **虎扑**：保留全部 60 个 segment，按时间排序输出为 Markdown 帖子格式，每个 segment 配 GIF 链接。模板结构为"比赛标题 + 简介 + 60 段战术分析（每段：时间 + 三段式分析 + GIF）+ 总评 + 数据表"。
- **抖音**：从 60 个 segment 中按"质量打分 × 时间分布"挑选 3-5 个回合，生成 30-60 秒的视频脚本。脚本包含口播文案、镜头时长建议、片头钩子文案。
- **微博**：选 1 个"最具传播价值"的金句（评估指标：包含数字 + 包含球员名 + 长度 < 80 字），附加 1 张 GIF 关键帧。
- **小红书**：选 6-8 个有视觉冲击力的回合，提取关键帧并配以软性叙述，构建"标题封面 + 6 张图 + 3 段文字"的图文模板。

### 4.6.1 质量打分

每个 segment 在生成时附带一个 0-100 的质量打分，作为多平台选择的核心依据。打分维度：

- 是否含具体战术名（+30 分）
- 是否含具体球员名（+20 分）
- 是否含具体数字（+15 分）
- 是否经过 Fact Checker 校验（+15 分）
- 是否落在播放段内（+10 分）
- 文本长度是否在合理范围（+10 分）

70 分以上视为高质量 segment，在虎扑发帖时优先呈现，在抖音/微博选择时优先入选。

## 4.7 网页评审界面（Tactical Review）

### 4.7.1 技术栈选择

前端采用 React 18 + Ant Design 5 + Babel-standalone 的 CDN 引入方案，不引入 npm 构建。这一选择的考虑：(1) 整个项目以 Python 后端为主，避免引入 Node.js 构建链；(2) Babel-standalone 支持 JSX 直接在浏览器编译，开发迭代极快；(3) Ant Design 提供成熟的中文 UI 组件库，覆盖大多数需求。

### 4.7.2 三栏布局

主页面采用三栏布局：

- **左栏**：60 个 clip 的时间轴列表，每个 clip 显示节次、时间码、质量打分、snap 状态（绿色 UNCHANGED / 黄色 SHIFTED / 红色 TRIMMED）；
- **中栏**：选中 clip 的 GIF 大图 + 6 张关键帧拼图；
- **右栏**：战术解说的三段式分析（observation / decision_analysis / win_loss_impact）+ evidence 引用链接。

### 4.7.3 人机协同筛选

用户可以对每个 clip 做"勾选 / × 删除 / ↺ 恢复"三种操作，删除状态通过 localStorage 持久化（刷新页面不丢失）。底部浮动 pill 显示"N 个回合已选"，点击"📋 复制虎扑草稿"按钮一键生成 Markdown 文本到剪贴板。

### 4.7.4 玻璃毛态视觉风格

为提升 demo 演示的视觉吸引力，前端采用"赛博朋克 + 玻璃毛态（glassmorphism）"的设计风格——半透明卡片背景、渐变光晕、网格底纹、流光数据条等元素。这一选择在硕士论文研究中虽非关键贡献，但显著提升了演示场景的产品感。

## 4.8 本章小结

本章给出了系统六个关键模块的具体实现细节，覆盖了从 PBP 接入到网页评审界面的端到端流水线。系统总代码量约 7000 行 Python（不含前端 React 代码与样式表）。下一章将给出基于该实现的多维度评估实验。

\newpage
