# Demo Data Rebuild Guide

本仓库只提交代码、配置样例、少量 sample 数据和评估 gold CSV。视频、真实 PBP、court report、OCR 时间图、GIF/MP4 切片、评估结果等都属于可重新生成产物，默认被 `.gitignore` 忽略。

## 1. 准备 Python 环境

在 `sports_agent/` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

然后在 `.env` 中填入自己的 LLM key。不要提交 `.env`。

## 2. 下载 NBA 官方 PBP

OKC vs LAL 2026 西部半决赛 G1 的 game id 是 `0042500221`。从 NBA 官方 CDN 拉取并归一化：

```powershell
.\.venv\Scripts\python.exe -m ingestion.nba_pbp_fetcher `
  --game-id 0042500221 `
  --output data\replays\okc_lal_west_semis_g1.json
```

也可以先列出最近 30 天季后赛比赛：

```powershell
.\.venv\Scripts\python.exe -m ingestion.nba_pbp_fetcher --list-recent-playoffs
```

## 3. 构造 demo court report

NBA 不公开本项目所需的场馆 AI 报告格式。demo 中的 court report 从官方 PBP 推导得到：

```powershell
.\.venv\Scripts\python.exe -m ingestion.court_report_builder `
  --replay data\replays\okc_lal_west_semis_g1.json `
  --output data\court_reports\0042500221_court_report.json
```

## 4. 手动准备视频文件

自行准备对应比赛的广播视频文件，放到：

```text
data/videos/nba_demo.MKV
```

视频文件体积很大，不提交到 git。文件名可以不同，但后续命令中的 `--video` 需要同步修改。

## 5. OCR 标定与视频时间映射

先标定比分牌 OCR ROI：

```powershell
.\.venv\Scripts\python.exe -m video_scout.scoreboard_roi_picker `
  --video data\videos\nba_demo.MKV `
  --output data\videos\nba_demo.scoreboard_roi.json
```

再构建全视频时间映射：

```powershell
.\.venv\Scripts\python.exe -m video_scout.video_time_mapper `
  --video data\videos\nba_demo.MKV `
  --roi data\videos\nba_demo.scoreboard_roi.json `
  --sample-interval-seconds 30 `
  --output data\videos\nba_demo.time_map.json `
  --visualize
```

如果需要视觉得分追踪，再标定分数 ROI：

```powershell
.\.venv\Scripts\python.exe -m video_scout.score_roi_picker `
  --video data\videos\nba_demo.MKV `
  --output data\videos\nba_demo.score_roi.json
```

并运行比分追踪、PBP 对账、可视化报告：

```powershell
.\.venv\Scripts\python.exe -m video_scout.scoreboard_score_tracker `
  --video data\videos\nba_demo.MKV `
  --score-roi data\videos\nba_demo.score_roi.json `
  --sample-interval 2.0 `
  --confirm-threshold 3 `
  --output data\videos\nba_demo.score_events_v2.json

.\.venv\Scripts\python.exe -m video_scout.pbp_score_reconciler `
  --score-events data\videos\nba_demo.score_events_v2.json `
  --replay data\replays\okc_lal_west_semis_g1.json `
  --time-map data\videos\nba_demo.time_map.json `
  --output data\videos\nba_demo.reconciliation_report.json

.\.venv\Scripts\python.exe -m video_scout.visual_score_report `
  --reconciliation data\videos\nba_demo.reconciliation_report.json `
  --output data\generated\visual_score\v2
```

## 6. 重跑端到端 demo

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner `
  --video data\videos\nba_demo.MKV `
  --replay data\replays\okc_lal_west_semis_g1.json `
  --court-report data\court_reports\0042500221_court_report.json `
  --auto-observations `
  --time-map data\videos\nba_demo.time_map.json `
  --apply-time-map `
  --refine-events `
  --use-llm `
  --output-dir data\generated\video_scout\real_okc_lal_g1_v3_neighbor
```

生成的 `report.json`、`report.md`、`clip_manifest.json`、GIF/MP4 切片都会在 `data/generated/` 下。

## 7. 运行社交媒体打包器

```powershell
.\.venv\Scripts\python.exe -m social_packager.demo_runner `
  --report data\generated\video_scout\real_okc_lal_g1_v3_neighbor\report.json `
  --clip-manifest data\generated\video_scout\real_okc_lal_g1_v3_neighbor\clip_manifest.json `
  --platforms hupu,douyin,weibo,xiaohongshu `
  --use-llm
```

输出目录形如：

```text
data/generated/social/<timestamp>/
  hupu/post.md
  hupu/package.json
  douyin/script.md
  douyin/package.json
  weibo/post.md
  weibo/package.json
  xiaohongshu/post.md
  xiaohongshu/package.json
  summary.json
```

## 8. 跑评估实验

mini gold：

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiment `
  --replay data\samples\nba_replay_sample.json `
  --court-report data\samples\court_ai_report_sample.json `
  --gold-boundaries evaluation\datasets\mini_gold_boundaries.csv `
  --gold-claims evaluation\datasets\mini_gold_claims.csv `
  --systems main,highlight_only,gpt_only `
  --runs 1 `
  --output evaluation\results\mini_validate
```

真实 gold 可替换为：

```text
evaluation/datasets/gold_boundaries.csv
evaluation/datasets/gold_claims.csv
```

并把 `--replay`、`--court-report` 指向 OKC-LAL G1 的真实 demo 数据。

## 9. 期望目录结构

```text
sports_agent/
  data/
    samples/                         # 已提交的小样例
    replays/                         # 忽略：NBA PBP 重新下载
    court_reports/                   # 忽略：由 PBP 推导
    videos/                          # 忽略：本地视频、ROI、time_map、score_events
    generated/                       # 忽略：报告、GIF、MP4、社交媒体包
  evaluation/
    datasets/                        # 已提交：mini_gold / gold CSV
    results/                         # 忽略：可重跑
  ingestion/
  video_scout/
  social_packager/
  webapp/
```

保留在 git 中的 `data/samples/` 和 `evaluation/datasets/gold_*.csv` 是工作区配置数据，不要删除。
