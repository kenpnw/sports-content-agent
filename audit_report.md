# T-101 video_scout 端到端审计报告

审计日期：2026-05-05

审计范围：`video_scout/*`、`data/samples/video_scout_observations_sample.json`、`data/samples/nba_replay_sample.json`、`data/samples/court_ai_report_sample.json`、`VIDEO_SCOUT_GUIDE.md`

本次任务只运行现有功能并生成审计报告，未修改任何代码。

## 1. 已验证可用

### 1.1 deterministic fallback 报告生成可用

运行命令：

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --output-dir data\generated\audit_t101\fallback
```

结果：成功。

输出文件：

- `data/generated/audit_t101/fallback/report.md`
- `data/generated/audit_t101/fallback/report.json`
- `data/generated/audit_t101/fallback/clip_manifest.json`
- `data/generated/audit_t101/fallback/observations.normalized.json`

质量检查：

- `report.md` 字符数：4896
- 报告章节：13 / 13 个目标章节齐全
- `evidence_index` 中 3 个 ID 均能对应回 `observations`
- `clip_manifest.json` 生成成功，状态为 `plan_only`
- GIF 规划已启用，3 个 clip 均包含 `.gif` 输出路径

### 1.2 `--court-report` 场馆 AI 报告输入可用

运行命令：

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --court-report data\samples\court_ai_report_sample.json --output-dir data\generated\audit_t101\court_report_fallback
```

结果：成功。

输出文件：

- `data/generated/audit_t101/court_report_fallback/report.md`
- `data/generated/audit_t101/court_report_fallback/report.json`
- `data/generated/audit_t101/court_report_fallback/clip_manifest.json`
- `data/generated/audit_t101/court_report_fallback/observations.normalized.json`

质量检查：

- `report.md` 字符数：6512
- 报告章节：13 / 13 个目标章节齐全
- `Player Tactical Profiles` 已生成
- `S. Curry`、`L. James`、`A. Davis`、`D. Green` 等球员数据已进入球员战术画像
- `S. Curry` 的视频证据能对应 `clip_q1_1120_gsw_high_pnr` 与 `clip_q4_0008_gsw_clutch_spacing`

### 1.3 不带真实视频时的 clip manifest graceful degrade 可用

运行命令：

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --video D:\nba_demo\missing_full_game.mp4 --observations data\samples\video_scout_observations_sample.json --court-report data\samples\court_ai_report_sample.json --output-dir data\generated\audit_t101\missing_video_plan
```

结果：成功。

输出文件：

- `data/generated/audit_t101/missing_video_plan/report.md`
- `data/generated/audit_t101/missing_video_plan/report.json`
- `data/generated/audit_t101/missing_video_plan/clip_manifest.json`
- `data/generated/audit_t101/missing_video_plan/observations.normalized.json`

质量检查：

- `clip_manifest.json` 状态为 `plan_only`
- 原因正确记录为视频文件不存在
- 3 个战术片段均保留 `mp4` 与 `gif` 输出路径
- 三个时间窗分别为 `6.0-23.0s`、`28.0-44.0s`、`2856.0-2876.0s`
- 时间窗与样例 observation 中的 `clip_start_seconds` / `clip_end_seconds` 一致

### 1.4 DeepSeek API 最小自测可用

运行命令：

```powershell
.\.venv\Scripts\python.exe -m realtime.llm_client
```

结果：成功。

观测结果：

- Provider：`deepseek`
- Model：`deepseek-chat`
- Latency：约 1.34s
- Tokens：prompt 30 / completion 23 / total 53

说明：`.env` 中的 DeepSeek key 可用，LLM 基础连接不是问题。

## 2. 发现的问题

### 2.1 `video_scout.demo_runner --use-llm --target-chars 2000` 路径不稳定

运行命令：

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --use-llm --target-chars 2000 --output-dir data\generated\audit_t101\llm_2000
```

外部命令在 180 秒超时。

但输出目录中仍生成了文件：

- `data/generated/audit_t101/llm_2000/report.md`
- `data/generated/audit_t101/llm_2000/report.json`
- `data/generated/audit_t101/llm_2000/clip_manifest.json`
- `data/generated/audit_t101/llm_2000/observations.normalized.json`

检查 `report.json` 后发现：

- `metadata.model = fallback_template`
- `metadata.fallback_reason = LLM tactical analysis failed; used deterministic fallback. Error: LLM call failed after 3 attempts: Request timed out.`

结论：DeepSeek API 本身可用，但 `video_scout` 长 JSON 报告生成路径当前会超时，并最终降级到 deterministic fallback。CLI 层没有清晰暴露“这次其实是 fallback”。

### 2.2 短 LLM 报告也出现超时

运行命令：

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --use-llm --target-chars 800 --output-dir data\generated\audit_t101\llm_800
```

结果：120 秒超时，且未生成 `llm_800` 输出目录。

结论：问题不只是 `target_chars=2000` 太长，更可能是当前 `video_scout` JSON schema prompt 对 DeepSeek 的响应稳定性不够友好，或者 LLM 请求超时控制没有在 CLI 层形成足够清晰的失败返回。

### 2.3 `--court-report` 已生成球员战术画像，但 MVP Analysis 未正确引用 MVP 数据

在 `court_report_fallback/report.md` 中，`Player Tactical Profiles` 能正确引用球员数据，例如：

- `S. Curry: 34分, 22次出手, 8助攻, 3失误, 正负值+9`
- `L. James: 29分, 19次出手, 9助攻, 4失误, 正负值-3`

但 `MVP Analysis` 显示：

```text
当前没有接入场馆 AI 的 MVP 数据，MVP 判断只能依赖视频观察和人工标注。
```

这与 `court_ai_report_sample.json` 中 `mvp = S. Curry` 不一致。

初步判断：`CourtReport.to_prompt_context()` 传入了 `mvp` 与 `mvp_line`，但 fallback 的 `_fallback_mvp_analysis()` 仍在读取 `mvp_player` 字段，导致 MVP 信息没有被正确消费。

### 2.4 当前 observations 样例过少，不足以支撑正式“全场战术复盘”

当前 `video_scout_observations_sample.json` 只有 3 个 observation：

- `clip_q1_1142_lal_spain_pnr`
- `clip_q1_1120_gsw_high_pnr`
- `clip_q4_0008_gsw_clutch_spacing`

这足够验证链路，但不够支撑论文/demo 中“每场比赛多个回合的系统性分析”。正式演示至少需要 8-12 个战术回合，覆盖：

- 3-5 个进攻发起回合
- 2-3 个防守轮转或失位回合
- 1-2 个末节关键选择
- 1-2 个与 MVP 结论直接相关的回合

### 2.5 `ffmpeg` 当前未安装，真实 mp4/GIF 生成未验证

运行 `ffmpeg -version` 失败，当前系统没有可用的 `ffmpeg`。

因此本次只能验证：

- clip planning
- mp4 路径规划
- gif 路径规划
- graceful degrade

尚未验证：

- 从真实 NBA 视频剪出 mp4
- 从真实 NBA 视频生成 gif
- GIF 在报告或前端中的实际预览效果

## 3. 建议的小修

### 3.1 修复 fallback MVP Analysis 读取字段

小修范围：`video_scout/tactic_analyzer.py`，预计 < 20 行。

建议：

- `_fallback_mvp_analysis()` 同时支持 `mvp_player` 与 `mvp_line`
- 当 `mvp_line` 存在时，直接用 `mvp_line` 生成 MVP 分析
- 避免 `--court-report` 明明传入 MVP，却显示“没有接入场馆 AI 的 MVP 数据”

### 3.2 CLI summary 增加 `llm_status` / `fallback_reason`

小修范围：`video_scout/demo_runner.py`，预计 < 30 行。

建议：

- 在 `summary` 中返回 `model`
- 返回 `fallback_reason`
- 返回 `llm_used_successfully: true/false`

这样用户运行 `--use-llm` 后能立刻知道是否真的用了 DeepSeek，而不是只看命令是否退出。

### 3.3 优化 LLM prompt 输出拆分

小修范围：`video_scout/tactic_analyzer.py`，预计 < 50 行。

建议：

- 把长报告生成拆成“先生成结构化短 JSON，再生成 full_analysis 文本”两步，或减少一次性 JSON schema 的字段数量
- 当前一次性要求 `full_analysis + key_segments + mvp_analysis + player_profiles + evidence_index`，对 DeepSeek JSON 模式压力较大
- 短期可先减少 `max_tokens` 与 prompt schema 描述，提升稳定性

### 3.4 调整 report.md 章节顺序

小修范围：`video_scout/demo_runner.py`，预计 < 10 行。

当前 `report.md` 中 `## Key Tactical Segments` 后立即插入 `## Tactical Clip Manifest`，阅读顺序略跳。

建议顺序：

1. Executive Summary
2. Full Tactical Analysis
3. Tactical Clip Manifest
4. Key Tactical Segments
5. Tactical Themes
6. Quarter / Flow Reading
7. Deciding Factors
8. MVP Analysis
9. Player Tactical Profiles
10. Limitations
11. Evidence Index

## 4. 建议的大改

### 4.1 建立自动回合边界检测器

对应下一任务：T-102。

当前 observations 仍依赖人工标注。要支撑论文创新点“战术回合自动切片”，必须从 NBA PBP 自动推断 possession boundary，再生成可剪辑时间窗。

建议产物：

- `video_scout/possession_boundary_detector.py`
- `boundaries_to_observations()`
- 自动输出 `clip_start_seconds` / `clip_end_seconds`

### 4.2 建立 auto_observation_builder

对应任务：T-103。

目标：从 PBP + 可选 court report 自动构建 observations，减少人工写 JSON 的工作量。

这一步完成后，主线可以变成：

```text
replay JSON + court report + optional video -> auto observations -> clip manifest -> tactical report
```

### 4.3 建立评估实验框架

对应任务：T-104。

当前没有量化评估。硕士论文需要至少覆盖：

- 回合边界 precision / recall / F1
- report claim fact accuracy
- end-to-end latency
- main system vs highlight-only baseline vs GPT-only baseline

### 4.4 建立战术复盘可视化页面

对应任务：T-105。

当前报告主要是 Markdown/JSON 文件。答辩 demo 需要一个强视觉页面：

- 左侧 clip/GIF 时间轴
- 中间长文战术报告
- 右侧证据展开
- verified / speculative / narrative 三态高亮

### 4.5 接回社交媒体内容终点

对应任务：T-107。

当前主链路仍停在战术报告与 clip manifest。根据项目北极星，终点必须是“平台原生社交媒体内容”。

建议后续将 `video_scout` 输出打包成：

- 虎扑长帖
- 抖音脚本 + GIF
- 微博短文 + GIF
- 小红书图文/GIF 卡片
- B 站长复盘脚本
