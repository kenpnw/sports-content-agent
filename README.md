# Sports Content Agent

This project is currently focused on one working MVP scenario:

- NBA postgame input
- Hupu article package generation
- Douyin short video script generation
- local control room frontend
- visible backend workflow timeline

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

You should get output under:

```text
data/generated/nba_postgame/<timestamp>/
```

Typical generated files:

- `summary.json`
- `hupu/package.json`
- `hupu/article.md`
- `hupu/publish/publish_payload.json`
- `douyin/package.json`
- `douyin/script.md`
- `douyin/publish/publish_payload.json`
- `assets/douyin_poster.png`

Note:

- `--fetch-today` uses the NBA official live scoreboard feed
- that feed follows the NBA game day context, not China local wording
- for example, Beijing time `2026-03-31` may correspond to NBA feed games dated `2026-03-30`


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

- [BEHAVIOR.md](/C:/Users/Administrator/Desktop/sports-content-agent/sports-content-agent/sports_agent/BEHAVIOR.md)
- [ROADMAP.md](/C:/Users/Administrator/Desktop/sports-content-agent/sports-content-agent/sports_agent/ROADMAP.md)
- [CONTENT_STYLE_GUIDE.md](/C:/Users/Administrator/Desktop/sports-content-agent/sports-content-agent/sports_agent/CONTENT_STYLE_GUIDE.md)
