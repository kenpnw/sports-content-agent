# Thesis Experiments — PowerShell 一键命令

> 这是在 Windows 端跑的实验脚本（沙盒网络不能直连 DeepSeek，所以必须在你 Windows 跑）。
> 跑完后结果 JSON 直接写在仓库里，Claude 自动接得到。
>
> 每个脚本都是一行 PowerShell。先 `cd` 到仓库根：
>
> ```powershell
> cd C:\Users\Administrator\Desktop\sports-content-agent\sports-content-agent\sports_agent
> ```

---

## 命令 1 · 重跑 v15 的 60 个 LLM segment（约 1-2 分钟）

```powershell
python -m thesis_scripts.rerun_v15_llm
```

**产出**：`data/generated/video_scout/real_okc_lal_g1_v16_full_llm/report.json`

这是答辩展示用的"全 LLM 生成"版本，覆盖了今天修好的"不强行套战术名" + 30+ 篮球术语库 prompt。

---

## 命令 2 · 三组 ablation 对比（约 5-10 分钟）

```powershell
python -m thesis_scripts.run_ablation
```

**产出**：`evaluation/results/thesis_ablation_v16/summary_table.md`

跑完直接把 markdown 表格粘进论文第 5 章。三组系统：`main` / `highlight_only` / `gpt_only`。

---

## 命令 3 · Gold-set 幻觉率评估（约 2-3 分钟）

```powershell
python -m thesis_scripts.eval_hallucination
```

**产出**：`evaluation/results/thesis_hallucination_v16/hallucination_table.md`

按 60 个 segment 逐条让 DeepSeek 做事实裁判。给你真实的 hallucination rate %，用于第 5 章核心数字。

---

## 命令 4 · 第二场比赛端到端跑通（约 30-60 分钟）

⚠️ **下载好视频之后才能跑**。需要三个参数：

```powershell
python -m thesis_scripts.run_second_game `
    --video-path "data/videos/<你下的视频>.mkv" `
    --game-id 0042400321 `
    --slug ind_cle_g3
```

参数说明：
- `--video-path`：视频文件路径
- `--game-id`：NBA 官方 game_id（10 位数字，比如 `0042400321`）
- `--slug`：简短标识符，给输出文件夹命名用（无空格，建议 `球队1_球队2_g几` 格式）

**找 game_id 方法**：去 https://www.nba.com/playoffs，点比赛进去，URL 里面的 `game/`后面那串就是 game_id。

**产出**：`data/generated/video_scout/real_<slug>_v1/`（report.json + clips/ 等）。这就是论文第 5 章泛化能力小节用的数据。

---

## 顺序建议

| 顺序 | 命令 | 时间 | 阻塞下游？ |
|------|------|------|-----------|
| 1 | `rerun_v15_llm` | 1-2 min | 阻塞 #3（幻觉率要用 v16） |
| 2 | `run_ablation` | 5-10 min | 独立 |
| 3 | `eval_hallucination` | 2-3 min | 需要先跑 #1 |
| 4 | `run_second_game` | 30-60 min | 独立，等你视频下完 |

**最快推荐**：开 3 个 PowerShell 窗口并行跑 #1 / #2 / #4，#1 跑完再开 #3。

---

## 跑完之后

把 4 个产物路径告诉 Claude 就行（或者直接 `git status` 让他看新文件）：

```
data/generated/video_scout/real_okc_lal_g1_v16_full_llm/
evaluation/results/thesis_ablation_v16/
evaluation/results/thesis_hallucination_v16/
data/generated/video_scout/real_<slug>_v1/
```

Claude 会把数字填进论文对应章节。

---

## 故障排查

**API key 不工作？** → 打开 `.env` 检查 `LLM_API_KEY` 是否还有效。去 https://platform.deepseek.com/usage 看余额。

**`run_second_game` 第 2/5 步 ROI 失败？** → 在 `tactical_review.html` 网页里手动框一下记分牌位置，导出 ROI JSON 重跑加 `--skip-roi`。

**报中文乱码？** → PowerShell 跑 `chcp 65001` 切 UTF-8。
