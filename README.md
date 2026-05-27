# Sports Content Agent

This project is currently focused on one working MVP scenario:

- NBA postgame input
- official NBA final-game fetching
- topic selection and ranking
- evidence-backed scoring
- local Fact Store
- local Text RAG layer
- prompt contracts and agent supervision
- Hupu article package generation
- Douyin short video script generation
- local control room frontend
- visible backend workflow timeline
- video scout tactical analysis demo

The current workflow reads a normalized postgame JSON file and writes local content artifacts.


## Current MVP

Input:

- one NBA postgame JSON file

Output:

- Hupu package
- Douyin package
- workflow summary JSON

Sample input file:

- [data/samples/nba_postgame_sample.json](/C:/Users/Administrator/Desktop/sports-content-agent/sports-content-agent/sports_agent/data/samples/nba_postgame_sample.json)


## Project Entry Point

Run the local control room:

```bash
python main.py --serve
```

Then open:

```text
http://127.0.0.1:8765
```

The control room lets you:

- start a live fetch workflow
- inspect each backend step
- see which game the topic engine selected
- inspect score breakdown and evidence claims
- inspect Fact Store and Text RAG retrieval results
- inspect prompt contracts and supervision reports
- preview Hupu and Douyin output
- inspect publish plans and generated assets

Run the CLI directly:

```bash
python main.py --input data\samples\nba_postgame_sample.json
```

Or fetch the latest completed NBA game from the official NBA live data feed:

```bash
python main.py --fetch-today --save-input
```

You can also target a specific team:

```bash
python main.py --fetch-today --team LAL --save-input
```

Run the Video Scout tactical analysis demo:

```bash
python -m video_scout.demo_runner --observations data\samples\video_scout_observations_sample.json --replay data\samples\nba_replay_sample.json --court-report data\samples\court_ai_report_sample.json --use-llm --target-chars 2000
```

This writes a timestamp-grounded tactical report under:

```text
data/generated/video_scout/<timestamp>/
```

The control room also supports `Video scout demo` from the source dropdown.

If a full NBA replay video is available, add `--video` to generate tactical clip plans or real clips:

```bash
python -m video_scout.demo_runner --video D:\nba_demo\full_game.mp4 --observations data\samples\video_scout_observations_sample.json --court-report data\samples\court_ai_report_sample.json --target-chars 2000
```

When `ffmpeg` is installed, each tactical possession can produce both an `mp4` clip and a lightweight `gif` preview.

You should get output under:

```text
data/generated/nba_postgame/<timestamp>/
```

Typical generated files:

- `summary.json`
- `selection.json`
- `hupu/package.json`
- `hupu/article.md`
- `hupu/publish/publish_payload.json`
- `douyin/package.json`
- `douyin/script.md`
- `douyin/publish/publish_payload.json`
- `assets/douyin_poster.png`

Note:

- `--fetch-today` uses the NBA official live scoreboard feed
- if you do not pass `--team`, the system now ranks all completed NBA games and picks the best topic of the day
- that feed follows the NBA game day context, not China local wording
- for example, Beijing time `2026-03-31` may correspond to NBA feed games dated `2026-03-30`


## Knowledge Layer

The project now maintains a lightweight local fact store at:

```text
data/knowledge/sports_facts.sqlite3
```

Current role of this database:

- cache normalized game facts
- build team recent-form summaries
- build simple head-to-head context
- build player tracked-form summaries
- support the topic engine and evidence layer

This is the first step toward a future `Fact Store + RAG Store` architecture:

- structured facts should come from tables
- narrative documents, recaps, and interviews can later go into a separate RAG layer


## Text RAG Layer

The project also supports local text retrieval from:

```text
data/knowledge/documents/
```

You can place:

- official recap markdown
- interview notes
- injury updates
- verified media reports

The Text RAG store chunks these documents and indexes them locally in SQLite FTS.


## Governance Layer

The project now includes a machine-readable governance policy:

```text
data/standards/governance.json
```

It defines:

- prompt constraints
- minimum evidence count
- minimum confidence thresholds
- RAG source priority
- agent boundaries
- review chain

The workflow uses these rules to generate:

- prompt contracts
- fact check reports
- risk review reports
- publish gating context


## Python Environment

Current minimal dependencies:

```txt
pillow
matplotlib
flask
```

They are defined in [requirements.txt](/C:/Users/Administrator/Desktop/sports-content-agent/sports-content-agent/sports_agent/requirements.txt).


## Rebuild Venv

If your environment is broken, rebuild it from the project root:

### Windows PowerShell

```powershell
cd C:\Users\Administrator\Desktop\sports-content-agent\sports-content-agent\sports_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py --input data\samples\nba_postgame_sample.json
```

If your system blocks PowerShell activation, use:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --input data\samples\nba_postgame_sample.json
```


## About `CREATE_VENV.PIP_FAILED_INSTALL_REQUIREMENTS`

This error means:

- the virtual environment was created
- but `pip install -r requirements.txt` failed inside that environment

It is only a wrapper error. The real cause is usually one of these:

1. old dependencies in a previous version of `requirements.txt`
2. network or mirror failure during install
3. permission or Python path problems
4. using the wrong project directory when creating the venv


## How To Debug Venv Install Failures

### 1. Confirm You Are In The Correct Directory

Use this directory:

```text
C:\Users\Administrator\Desktop\sports-content-agent\sports-content-agent\sports_agent
```

This is the directory that contains:

- `main.py`
- `requirements.txt`
- `README.md`


### 2. Inspect `requirements.txt`

Current file is intentionally minimal.

If you see a different local copy with extra packages, that may be the reason installation is failing.


### 3. Run Pip Manually

Inside the venv, run:

```powershell
python -m pip install -r requirements.txt
```

This usually prints the actual package or network error.


### 4. Upgrade Pip First

```powershell
python -m pip install --upgrade pip
```

Older pip versions can fail on wheel resolution.


### 5. Remove And Recreate The Venv

If the environment is half-created, delete it and start clean.

Suggested venv name:

- `.venv`

Avoid mixing:

- old `venv/`
- new `.venv/`
- global Python site-packages


## Common Fixes

### Pip Timeout Or Download Failure

Try again later or switch to a working mirror if your environment uses one.


### Wrong Python Executable

Check:

```powershell
python --version
python -m pip --version
```

Make sure both point to the same interpreter you expect.


### Package Installs Globally But Not In Venv

That usually means:

- the venv interpreter is not the one being used
- or the activation step did not actually take effect

Use the explicit interpreter path inside `.venv\Scripts\python.exe`.


## Recommended Working Mode

For now, treat this project as:

- local generation first
- real data ingestion next
- publish plan preparation now
- credential-gated live posting later

Do not depend on the old PDF workflow for the new MVP path.


## Platform Publishing Status

## Social Packager

`social_packager` turns a Video Scout tactical report plus GIF clip manifest into platform-native content packages for Hupu, Douyin, Weibo, and Xiaohongshu. It does not publish to any real account; it writes Markdown plus `package.json` for manual review.

```powershell
.\.venv\Scripts\python.exe -m social_packager.demo_runner ^
  --report data\generated\video_scout\real_okc_lal_g1_v3_neighbor\report.json ^
  --clip-manifest data\generated\video_scout\real_okc_lal_g1_v3_neighbor\clip_manifest.json ^
  --platforms hupu,douyin,weibo,xiaohongshu ^
  --use-llm
```

Output:

- `data\generated\social\<timestamp>\hupu\post.md`
- `data\generated\social\<timestamp>\douyin\script.md`
- `data\generated\social\<timestamp>\weibo\post.md`
- `data\generated\social\<timestamp>\xiaohongshu\post.md`
- `data\generated\social\<timestamp>\summary.json`

### Hupu

- content generation is ready
- publish payload generation is ready
- workflow supports manual review posting
- no verified public official Hupu posting API is wired in this repo

### Douyin

- content generation is ready
- poster asset generation is ready
- publish payload generation is ready
- live official posting still requires approved Douyin open platform credentials


## Related Docs

- [README_DEMO_DATA.md](README_DEMO_DATA.md) — sample data + replay walkthrough
- [VIDEO_SCOUT_GUIDE.md](VIDEO_SCOUT_GUIDE.md) — video pipeline (OCR, scoreboard, time map, clip alignment)
- [evaluation/README.md](evaluation/README.md) — ablation harness and gold sets
