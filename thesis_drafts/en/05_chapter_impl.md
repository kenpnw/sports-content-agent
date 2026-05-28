# Chapter 4  Key Technical Implementation

This chapter presents the concrete implementation of six key modules in the system. Section 4.1 covers NBA Live API ingestion. Section 4.2 details video time mapping. Section 4.3 covers scoreboard visibility detection. Section 4.4 describes tactical clip alignment and extraction. Section 4.5 covers tactical commentary generation. Section 4.6 covers multi-platform social packaging. Section 4.7 covers the web review interface.

## 4.1 NBA Live API Ingestion and Play-by-Play Parsing

### 4.1.1 Ingestion Challenges

NBA's public Live API (https://cdn.nba.com/static/json/liveData/...) is publicly accessible but lacks official documentation and is sensitive to request headers — calling with Python `requests`' default User-Agent returns HTTP 403 Forbidden. We solve this in two steps:

1. **Browser-class header simulation.** The User-Agent is set to a standard Chrome browser string, accompanied by `Referer: https://www.nba.com/`, `Accept-Language: en-US`, `Accept: application/json`, simulating a browser environment;
2. **Multi-endpoint redundancy.** Besides the primary `playbyplay/playbyplay_<game_id>.json` endpoint, we fall back to `boxscore/boxscore_<game_id>.json` as a validation cross-check, avoiding total failure on single-endpoint outages.

### 4.1.2 Game Selection

The system supports two game-selection paths:

- **Today's games**: call the `scoreboard/todaysScoreboard_00.json` endpoint to get all games today;
- **Recent N days**: call the `scheduleLeagueV2_1.json` endpoint to get the season's full schedule, then filter to the last N (default 30) days of completed events. The webapp console exposes a "refresh recent 30 days" button for demo-time game selection.

### 4.1.3 Play-by-Play Parsing

NBA Live API returns PBP as a nested JSON structure with each event containing ~30 fields. Our `nba_pbp_fetcher` module normalizes them into the internal `replay_event` data structure, with key fields:

- `period` (1–4 or 5+ for overtime)
- `clock` (remaining game clock as ISO 8601 duration, e.g., `PT10M51.00S`)
- `action_type` (2pt / 3pt / freethrow / rebound / turnover / steal / block / foul / ...)
- `description` (human-readable, e.g., `"L. James 26' 3PT running pullup (5 PTS)"`)
- `player_id` / `team_id`
- `score_home` / `score_away`

### 4.1.4 Observation Construction

The `possession_boundary_detector` module identifies "possession boundaries" from the normalized event sequence and filters "high-content-value possessions" by rule:

- Any scoring possession (made_shot)
- High-impact turnovers
- Critical defensive plays (block, steal)
- Closing-time possessions (last 2 minutes)

On OKC vs LAL G1, the rule engine reduces the original 500–700 PBP events to about 60 observations covering a representative tactical sample of the game (rather than a pure highlight reel).

## 4.2 Video Time Mapping

### 4.2.1 Frame Sampling Strategy

The video time mapping module aims to build a "video-seconds ↔ game-clock" mapping function. Construction depends on sampling one frame per second from the video and applying OCR. We compared two implementation approaches:

- **Approach A: OpenCV random seek.** Use `cv2.VideoCapture` with `cap.set(cv2.CAP_PROP_POS_FRAMES, k)` to seek to the k-th second. This is acceptable on MP4 but extremely slow on MKV due to wide keyframe intervals (each seek takes hundreds of milliseconds).
- **Approach B: ffmpeg pipeline streaming.** Use `ffmpeg -i video.mkv -vf fps=1 -f image2pipe -pix_fmt bgr24 -vcodec rawvideo -` to decode at 1fps and stream the result through a pipe to the Python process, where OpenCV directly parses via `np.frombuffer`.

On a 7.5GB OKC vs LAL G1 MKV file, Approach A averages 400–800ms per random seek, totaling 1.5–2 hours for 9000 seconds. Approach B completes in 8–10 minutes — about 12–15× faster. We adopt Approach B as our production approach.

### 4.2.2 OCR Implementation

The scoreboard region (ROI) of each frame is pre-calibrated by the user (coordinates stored in `<video>.scoreboard_roi.json`), typically located in the horizontal strip at 78%–97% of the screen height. OCR is performed on this ROI:

- **OCR engine**: EasyOCR (a deep-learning multi-language OCR library) with reasonable Chinese-English mixed recognition;
- **Preprocessing**: grayscale + adaptive thresholding to improve scoreboard-digit contrast;
- **Post-processing**: regex extraction of the four fields ("period, home score, away score, remaining clock"), with implausible values (e.g., clock 99:99) filtered out.

Successful recognition covers about 60–70% of samples (the rest correspond to moments when the scoreboard is hidden or occluded). On OKC vs LAL G1, 95 valid samples are obtained from 9000 samplings, spread across the 4 periods.

### 4.2.3 Piecewise Linear Interpolation

Per-period piecewise-linear mapping is constructed from "video-seconds ↔ game-clock-remaining":

```python
def video_seconds_for(period, target_clock_seconds):
    samples = ocr_samples_for_period(period)
    samples.sort(key=lambda s: s.clock_remaining_seconds)
    # Find two samples bracketing target_clock_seconds
    # and linearly interpolate their video_seconds.
    ...
```

Key bug encountered in practice:

- **Early bug**: the earlier version did not segregate samples by period. As a result, Q1 and Q2 samples were jointly fitted, producing 1000+-second alignment errors near period boundaries.
- **Fix**: in `_apply_time_map`, first group by period, then do linear interpolation per period. Post-fix, errors fell to within 30 seconds across the OCR-sample-covered range.

## 4.3 Scoreboard Visibility Detection

### 4.3.1 Design Approach

Scoreboard visibility detection aims to classify each video second as "play" (scoreboard visible → game in progress) or "non-play" (scoreboard hidden → replay, slow motion, commercial). We use OpenCV template matching to avoid the deployment cost of deep-learning inference.

### 4.3.2 Template Extraction and Matching

- **Template extraction**: from 4 periods × 3 time points each, we extract scoreboard ROI regions, yielding 12 reference templates. This covers minor in-period visual variations (digit position shifts from score changes, advertising overlay appearances/disappearances).
- **Matching algorithm**: for each per-second sampled frame, the ROI is compared against all 12 reference templates using `cv2.matchTemplate(method=cv2.TM_CCOEFF_NORMED)`, taking the maximum as that second's visibility score.
- **Threshold and smoothing**: an empirical threshold of 0.65 separates visible from hidden. The raw signal contains single-frame noise (e.g., transition-instant misjudgments); we median-filter with a 3-second window to produce the final `scoreboard_visibility_v2_smoothed.json`.

### 4.3.3 Evolution of Detection Accuracy

We iterated on the detector across two versions:

- **v1 (single template)**: only one reference template per period, 4 total. Result: non-play frames (especially coach close-ups and player portraits) also score high, making play segments overly permissive — 87% of OKC vs LAL G1 video time is marked play, 27 percentage points higher than the true 60%.
- **v2 (dense templates + game-window filter)**: 3 templates per period (12 total) plus a hard rule that "first 5 minutes pre-game + last 5 minutes post-game must be non-play." Improved to 60% play, matching manual annotation.

We adopt v2 as final.

## 4.4 Tactical Clip Alignment and Extraction

### 4.4.1 Alignment Strategy

Each observation, after Section 3.2.2's three-step process, has its expected video time determined. We then specify the clip's exact time window based on three factors:

- **Event-position normalization**: the event is placed at the 78% position of the clip (so only 22% remains as follow-out). This ratio is based on observation of human editors' highlight pacing.
- **Adaptive window length**: default window 10 seconds (8s lead-in, 2s follow-out); fast-break possessions extend to 12 seconds; free-throw possessions shrink to 6.
- **Play-segment snap**: if the initial window falls in a non-play segment, snap to the nearest play segment per Section 3.2.2 strategy.

### 4.4.2 Edge Cases

Several edge cases required special handling in practice:

- **Period-end / game-end events**: events with clock < 15 seconds may have no OCR sample coverage. For these, snap is skipped, best-effort linear extrapolation is used, and `extrapolated=true` is set in clip metadata;
- **Clip window exceeding video duration**: an early version did not check, producing zero-byte clip files. The fix clamps windows to `[0, video_duration]` before ffmpeg cuts;
- **Duplicate events**: a single second may contain multiple PBP events (e.g., score + assist + three-made on consecutive events). We merge these into a single clip to avoid duplicates.

### 4.4.3 ffmpeg Cutting and GIF Generation

Once the clip window is determined, ffmpeg generates both an MP4 clip and a GIF animation:

```bash
# MP4 clip
ffmpeg -ss <start> -t <duration> -i <video> -c copy <output>.mp4

# GIF (for web display, single GIF ~500KB-1MB)
ffmpeg -ss <start> -t <duration> -i <video> -vf "fps=10,scale=480:-1" <output>.gif
```

Each clip also has `extract_clip_frames` called to extract 6 key frames (evenly distributed, biased toward the second 50% segment) for web display.

## 4.5 Tactical Commentary Generation

### 4.5.1 Four-Stage Pipeline

The `tactic_analyzer.VideoScoutAnalyzer.analyze` method implements the concrete invocation sequence of the 5-Agent protocol, in 4 LLM-call stages:

- **Stage 1 (overview generation)**: based on the overview of all 60 observations, generates the report's `title`, `executive_summary`, `tactical_themes` fields;
- **Stage 2 (key_segments generation)**: for each observation, calls the Writer role to generate the observation / decision_analysis / win_loss_impact triple. This is the longest stage, taking 60–70 seconds for 60 segments.
- **Stage 3 (quarter_flow and deciding_factors)**: based on Stage 2 output, generates per-period game flow and outcome-determining factor analysis;
- **Stage 4 (content_angles and player_decision_notes)**: generates multi-platform content suggestions and player-decision commentary.

Each stage internally follows the standard flow "Prompt Contract construction → LLM call → output parsing → Fact Checker review → Risk Guard review."

### 4.5.2 Basketball Glossary Injection

The Writer role's system prompt explicitly injects a 30+-term Chinese-English basketball glossary:

```
- 1-5 PnR / High PnR: pick-and-roll between the 1 and 5
- Spain PnR: 3-player PnR variant, screener gets screened
- Hammer: weak-side baseline screen + cross-court pass
- Backdoor cut: reverse cut when defender overplays
- Horns set: double-elbow staggered initial alignment
... (30+ entries total)
```

This injection biases the LLM toward professional terminology over generic "screen" or "play."

### 4.5.3 The "Do Not Force Tactical Labels" Negative Rule

In production we observed the LLM tendency to force a tactical label onto every possession (even turnovers, free throws, period-end winddowns), making the commentary feel naive. We added a "strict prohibition" rule to the prompt:

```
**STRICT PROHIBITION: do not force a tactical label on**:
・Any turnover (turnover/bad pass/lost ball/...) → write "turnover possession, cause: XX," not "this is XX tactic"
・Period end / game end → write "Qn closing time" or "game over"
・Individual ISO with random dribbling and a shot → individual ability, not tactic
・Putback / second-chance scoring → just "second chance," no need to tacticize
・Free throws → "free-throw moment"
・Transition / fast-break without clear tactical pattern → "transition" suffices, no need to force a half-court tactical name
```

After adding this rule, the LLM's use of tactical names became more restrained and professional.

### 4.5.4 LLM Call Engineering Details

- **API provider**: DeepSeek (OpenAI-compatible interface)
- **Model selection**: `deepseek-chat` (suitable for most tasks) + `deepseek-reasoner` (enabled on demand only for Stage 1 deeper analysis)
- **Hyperparameters**: `temperature=0.6`, `max_tokens=400` per segment, `top_p=0.9`
- **Retry policy**: API calls retry 3× on timeout (default 20s) or 5xx responses; output parsing failures regenerate (max 2 times); consecutive failures fall back to template fill.

## 4.6 Multi-Platform Social Packaging

The `social_packager` module follows Section 3.7.2's strategies. Per-platform implementation highlights:

- **Hupu**: preserves all 60 segments, time-ordered, output as Markdown post format with GIF link per segment. Template: "game title + intro + 60 tactical analyses (each: time + three-section + GIF) + overall verdict + statistics table."
- **Douyin**: selects 3–5 possessions by "quality score × time distribution," generating a 30–60-second script with voice-over text, suggested shot lengths, and intro hook.
- **Weibo**: selects 1 "most quotable" line (must include number, player name, ≤80 chars) plus a GIF keyframe.
- **Xiaohongshu**: selects 6–8 visually striking possessions, extracts keyframes, accompanies with soft narrative, producing a "cover + 6 images + 3 caption paragraphs" template.

### 4.6.1 Quality Scoring

Each segment receives a 0–100 quality score at generation time, used as the core decision input for multi-platform selection. Scoring dimensions:

- Contains a specific tactical name (+30)
- Contains a specific player name (+20)
- Contains a specific number (+15)
- Passes Fact Checker (+15)
- Falls within a play segment (+10)
- Text length in reasonable range (+10)

Segments scoring 70+ are treated as high-quality, prioritized in Hupu posts and preferred for Douyin/Weibo selection.

## 4.7 Web Review Interface (Tactical Review)

### 4.7.1 Tech-Stack Choice

The frontend uses React 18 + Ant Design 5 + Babel-standalone via CDN, with no npm build. This choice reflects: (1) the project is Python-backend dominant; avoiding a Node.js build chain reduces complexity; (2) Babel-standalone supports in-browser JSX compilation, enabling rapid iteration; (3) Ant Design provides a mature Chinese-language UI component library covering most needs.

### 4.7.2 Three-Column Layout

The main page uses a three-column layout:

- **Left column**: 60 clips on a vertical time-axis list; each clip shows period, time code, quality score, and snap status (green UNCHANGED / yellow SHIFTED / red TRIMMED);
- **Center column**: the selected clip's GIF preview + 6 key-frame tile;
- **Right column**: the segment's three-section tactical commentary (observation / decision_analysis / win_loss_impact) plus evidence reference links.

### 4.7.3 Human-AI Collaborative Filtering

The user can perform three actions on each clip: "select / × delete / ↺ restore." Deletion state is persisted via `localStorage` (survives page reload). A floating pill at the bottom shows "N possessions selected"; clicking "📋 Copy Hupu draft" generates Markdown to clipboard.

### 4.7.4 Glassmorphism Visual Style

To enhance demo visual appeal, the frontend adopts a "cyberpunk + glassmorphism" design: semi-transparent card backgrounds, gradient halos, grid undertones, flowing data bars. While not the core academic contribution, this choice significantly improves the "product feel" during defense presentations.

## 4.8 Chapter Summary

This chapter has presented concrete implementation details for the six key modules, covering the end-to-end pipeline from PBP ingestion to the web review interface. Total system code is ~7000 lines of Python (frontend React code and stylesheets not counted). The next chapter presents multi-dimensional evaluation experiments based on this implementation.

\newpage
