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
