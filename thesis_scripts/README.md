# Thesis Experiments — PowerShell 一键命令

> 设计目标：你只提供视频文件，其他**全自动**。沙盒网络拿不到 NBA / DeepSeek，所以这些脚本得在 Windows 跑。

每个脚本都是一行命令。先 `cd` 到仓库根：

```powershell
cd C:\Users\Administrator\Desktop\sports-content-agent\sports-content-agent\sports_agent
```

---

## 🎯 主命令 · `run_game.py` — 跑任意一场比赛的完整流水线

```powershell
python -m thesis_scripts.run_game --video "C:\path\to\game.mkv"
```

**你只给视频**。脚本自动完成：

1. 从视频文件名嗅探球队 + 日期（支持中英文，如 `马刺_雷霆_g5.mkv` 或 `SAS_OKC_20260527.mkv`）
2. 拉 NBA 官方赛程，匹配到具体 game_id
3. 若唯一匹配 → 直接开跑；若多个候选 → 弹出 1 行编号选择器
4. 自动生成 slug（如 `sas_okc_20260527`）
5. PBP 拉取 → ROI 自动标定 → 可见性检测 → OCR 时间映射 → 60 clip 切片 → 5-Agent LLM 分析 → 4 平台打包

**总耗时约 30-60 分钟**（视频解析占大头）。结果在 `data/generated/video_scout/real_<slug>_v1/`。

### 可选覆盖（autodetect 出错时才用）

```powershell
python -m thesis_scripts.run_game --video <path> --game-id 0042500314
python -m thesis_scripts.run_game --video <path> --slug my_slug
python -m thesis_scripts.run_game --video <path> --date 2026-05-27
python -m thesis_scripts.run_game --video <path> --no-prompt     # CI 模式，多个候选时直接失败
python -m thesis_scripts.run_game --video <path> --skip-roi      # 复用已有的 ROI JSON
```

---

## 实验类命令（论文用）

### 1 · 重跑 v15 的 60 个 LLM segment（约 4 分钟）

```powershell
python -m thesis_scripts.rerun_v15_llm
```

产出：`data/generated/video_scout/real_okc_lal_g1_v16_full_llm/report.json`

### 2 · 三组 ablation 对比（约 5-10 分钟）

```powershell
python -m thesis_scripts.run_ablation
```

产出：`evaluation/results/thesis_ablation_v16/summary_table.md`

### 3 · Gold-set 幻觉率评估（约 2-3 分钟）

```powershell
python -m thesis_scripts.eval_hallucination
```

产出：`evaluation/results/thesis_hallucination_v16/hallucination_table.md`

### 4 · 查 game_id（辅助工具）

```powershell
python -m thesis_scripts.find_game_id --team SAS --lookback 14
```

通常不需要单独跑 —— `run_game.py` 已经内嵌了这一步。

---

## 跑完之后

把产出路径告诉 Claude（或直接 `git status` 让他看新文件）：

```
data/generated/video_scout/real_<slug>_v1/
evaluation/results/thesis_ablation_v16/
evaluation/results/thesis_hallucination_v16/
```

Claude 会把数字填进论文对应章节。

---

## 故障排查

**API key 不工作？** → `.env` 检查 `LLM_API_KEY`，去 https://platform.deepseek.com/usage 看余额。

**autodetect 找不到比赛？** → 用 `python -m thesis_scripts.find_game_id --team <球队> --lookback 30` 手动查 game_id，再用 `--game-id` 传给 `run_game.py`。

**PowerShell 中文乱码？** → 跑 `chcp 65001` 切 UTF-8。
