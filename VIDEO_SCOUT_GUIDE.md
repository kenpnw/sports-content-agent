# Video Scout Agent Guide

This module adds a video-based tactical analysis path to the project.

Current goal:

- use local game clips, sampled frames, or annotated observations
- align them with play-by-play context when available
- generate a tactical report with timestamps and evidence
- reuse DeepSeek for the final basketball analysis

## What It Can Do Now

The first MVP can:

- read a prepared observation JSON
- optionally read a play-by-play replay JSON
- generate a tactical report with key segments, player decisions, win/loss causes, and content angles
- write `report.json`, `report.md`, and normalized observations
- optionally sample frames from a local video if `opencv-python` is installed
- optionally call an OpenAI-compatible vision model if `VISION_API_KEY` is configured

## Recommended Demo Path

Use the sample observation file first:

```powershell
cd C:\Users\Administrator\Desktop\sports-content-agent\sports-content-agent\sports_agent
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --use-llm
```

Output will be written under:

```text
data/generated/video_scout/<timestamp>/
```

Open:

- `report.md`
- `report.json`

For a longer scouting report, use:

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --use-llm --target-chars 2000
```

If you also have a smart-court AI box-score report, add:

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --court-report data\samples\court_ai_report_sample.json --use-llm --target-chars 2000
```

The court report adds:

- player shot attempts and makes
- points, rebounds, assists, steals, blocks, turnovers
- MVP result
- player tactical initiation score
- player role interpretation, such as primary initiator, screen hub, finisher, spacer, or defensive organizer

## NBA Full Replay To Tactical Clips

Your current target can be described as:

```text
NBA broadcast replay -> possession-level tactical clips -> tactical report
```

The observations file is the bridge between the full broadcast video and the tactical report. Each observation can define:

- `timecode_seconds`: the event timestamp in the full video
- `clip_start_seconds`: where the tactical possession clip should begin
- `clip_end_seconds`: where the clip should end
- `clip_label`: the output clip name
- `tactic_tags`: high pick-and-roll, transition defense, weak-side spacing, etc.
- `players`: players involved in the possession

Run with a video path:

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --video D:\nba_demo\full_game.mp4 --observations data\samples\video_scout_observations_sample.json --court-report data\samples\court_ai_report_sample.json --target-chars 2000
```

If `ffmpeg` is installed, clips are written under:

```text
data/generated/video_scout/<timestamp>/clips/
```

Each tactical possession will produce:

- `001_xxx.mp4`: the original tactical clip
- `001_xxx.gif`: the lightweight animated GIF for reports, frontend previews, or PPT

If `ffmpeg` is not installed, the system still writes:

```text
clip_manifest.json
```

This file is the tactical clipping plan: every row says which possession should be cut, from which second to which second, and why.

GIF generation is enabled by default. You can tune it:

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --video D:\nba_demo\full_game.mp4 --observations data\samples\video_scout_observations_sample.json --court-report data\samples\court_ai_report_sample.json --gif-fps 10 --gif-width 480
```

Disable GIF output:

```powershell
--no-gif
```

For your thesis/demo, this is a strong framing:

```text
The system does not merely generate highlights. It converts broadcast replay into possession-level tactical evidence.
```

By default this uses the faster `deepseek-chat` model. If you want slower but deeper reasoning, add:

```powershell
--use-reasoner
```

For a real demo, the best input is not a full 2-hour video at once. Prepare:

- 8-12 important possessions
- 3-5 offensive sets
- 2-3 defensive breakdowns
- 1-2 late-game decision points
- each clip should have period, clock, score, possession team, action summary, and evidence

With fewer than 5 observations, the system will go deeper on available possessions but should not invent missing plays.

## Add A Real Video Later

Install optional video extraction dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install opencv-python
```

Sample frames:

```powershell
.\.venv\Scripts\python.exe -m video_scout.frame_sampler --video D:\nba_demo\game_clip.mp4 --output-dir data\generated\video_frames\game_clip --every-seconds 8 --max-frames 80
```

This creates:

```text
data/generated/video_frames/game_clip/frame_manifest.json
```

If you do not have a vision model configured, manually annotate the important frames into an observation JSON using `data/samples/video_scout_observations_sample.json` as the template.

## Optional Vision Model

The system is designed to support any OpenAI-compatible vision model.

Add these to `.env` only when ready:

```env
VISION_API_KEY=your_vision_api_key
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=gpt-4o-mini
VISION_TIMEOUT_SECONDS=30
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m video_scout.demo_runner --frame-manifest data\generated\video_frames\game_clip\frame_manifest.json --use-vision --use-llm
```

## Thesis Framing

Use this module as:

```text
Video-grounded tactical analysis agent
```

Academic contribution:

- video observations are grounded by timestamps and frame paths
- tactical claims are constrained by evidence
- generated explanations are connected to play-by-play and structured data
- the output can feed the existing platform content pipeline later

Do not describe this as a fully trained NBA video model yet. The honest and stronger framing is:

```text
A modular video-scouting pipeline with pluggable vision models and evidence-grounded tactical generation.
```

## OCR 时间对齐：第一步 ROI 标定

广播视频经常包含热身、采访、广告、暂停和中场内容，导致官方 PBP 的比赛时间无法直接线性映射到视频秒数。OCR 时间对齐会先读取比分牌上的节次和比赛计时，再把视频画面与 PBP 时间轴对齐；第一步就是人工标定比分牌 ROI，让后续 OCR 只识别稳定的文字区域。

运行交互式 ROI 标定：

```powershell
.\.venv\Scripts\python.exe -m video_scout.scoreboard_roi_picker `
  --video data\videos\nba_demo.mkv `
  --frame-at-seconds 120 `
  --output data\videos\nba_demo.scoreboard_roi.json `
  --visualize
```

ROI 选择技巧：

- 拖选范围比比分牌文字区域略大 5-10px，给 OCR 留余量。
- 不要包含台标、球队 logo、转播装饰条或无关图形，只圈节次、时间、比分等文字区域。
- 如果比分牌位置在视频中跳动，使用 `--frame-at-seconds` 找一个比分牌最稳定、遮挡最少的时刻重新标定。

标定完成后，打开生成的 `*.scoreboard_roi_preview.png`，确认红框完整包住比分牌文字区域。确认无误后，后续 OCR 阶段会复用同一个 `*.scoreboard_roi.json`。

## OCR 时间对齐：第二步 单帧 OCR 测试

完成 T-OCR-1 的 ROI 标定后，先不要立刻跑全视频采样。应该用单帧 OCR 工具验证：当前 ROI 是否能稳定读出比分牌文字，并且能把文字解析成结构化的节次和比赛剩余时间。

运行单帧 OCR 测试：

```powershell
.\.venv\Scripts\python.exe -m video_scout.scoreboard_ocr `
  --video data\videos\nba_demo.mkv `
  --roi data\videos\nba_demo.scoreboard_roi.json `
  --frame-at-seconds 1033
```

预期输出是 JSON，包含：

```json
{
  "raw_text": "Q1 11:42",
  "period": 1,
  "clock_remaining_seconds": 702.0,
  "confidence": 0.82,
  "error_reason": "",
  "ocr_box_count": 1
}
```

结果解读：

- 如果能读出文字，且 `period` / `clock_remaining_seconds` 正确，说明 ROI 可用，可以进入 T-OCR-3。
- 如果 `raw_text` 乱码或 `error_reason` 是 `no_text_detected`，通常是 ROI 偏了，回到 T-OCR-1 重新标定。
- 如果文字读到了但 `error_reason` 是 `parse_failed: ...`，把 `raw_text` 贴给协作者，需要新增解析规则。
## OCR 时间对齐：第四步 端到端切片

完成 `video_time_map.json` 后，可以把 OCR 检测出的每节开场锚点接入 `demo_runner`。这样自动 PBP observation 的全场累计比赛秒数会被重新映射到真实广播视频秒数，再用默认 22 秒 before / 4 秒 after 窗口切出战术回合 mp4 和 GIF。

```powershell
python -m video_scout.demo_runner ^
  --video data\videos\nba_demo.MKV ^
  --replay data\samples\nba_replay_sample.json ^
  --court-report data\samples\court_ai_report_sample.json ^
  --auto-observations ^
  --time-map data\videos\nba_demo.time_map.json ^
  --apply-time-map ^
  --use-llm
```

注意：`--apply-time-map` 必须显式开启，避免手动标注 observation 的 clip 时间被意外覆盖。如果某一节 anchor 缺失或标记为不可靠，系统会保留该 observation 原有 clip 时间并打印 warning。
