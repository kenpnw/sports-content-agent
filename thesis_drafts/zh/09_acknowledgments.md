# 致 谢

三年的硕士学习即将告一段落，回望来路，受惠于诸多师长、家人与朋友的支持，谨在此致以最诚挚的感谢。

首先，感谢我的导师 [导师姓名] 教授。从研究方向选择到论文最终成稿的每一个阶段，导师始终以严谨的学术态度与开放的学术胸怀指导我前行。在系统初版架构方向选择的关键时刻，导师建议"先做出一个完整端到端的系统，再去优化某一具体模块"的方法论指导，让我避开了"过早优化"的陷阱，将工程能力与研究价值并重。

感谢实验室 [实验室名称] 的全体同门。在多次组会汇报中，同门们提出的尖锐问题（如"幻觉率如何量化"、"为什么不直接用 GPT-4"、"对齐准确率为什么不是 100%"）一次次推动我把含糊的论述推到清晰的工程指标。感谢 [师兄/师姐] 在 RAG 系统设计上的经验分享；感谢 [师弟/师妹] 在视频处理流水线调试上的协助。

感谢 [合作公司或开源社区名称]。本研究中使用的 DeepSeek 大语言模型 API、NBA Live 公开 API、EasyOCR 开源库、OpenCV 视觉处理库等基础设施，是本工作得以实现的技术基石。在 AIGC 工程化落地的开放生态下能完成本研究，深感"站在巨人肩膀上"。

感谢 Paradoox AI 团队在我面试过程中给出的高标准技术问题与同等高水准的反馈。本研究的若干工程决策（如"评审角色不应该用同一个 LLM"、"Prompt Contract 而非 Prompt Engineering"）受到了该团队同事的直接启发，让我从"如何写一个能用的系统"上升到"如何写一个可信的系统"。

感谢父母与家人。在过去三年间他们始终给予无条件的情感支持与物质保障，使我能够专注于学业。感谢我的伴侣 [姓名] 在我连续多个深夜调试代码、推翻重写、再次推翻再次重写的过程中给予的理解与陪伴。

最后，感谢 NBA 这项运动以及它背后无数球员、教练、解说员、内容创作者共同构成的篮球文化生态。是这份对篮球的热爱，让我在面对漫长的工程调试时仍能保持兴奋——每一次看到自己的系统准确识别出一次"Spain PnR"或一记反弹三分，都是工程之外的双倍喜悦。

谨以此论文献给每一位在球场内外为这项运动倾注热情的人。

[作者姓名]\
[年] 年 [月] 月\
[学校所在城市]

\newpage

# 附录 A  v15 → v16 Prompt 迭代效果证据

本附录提供第 5.5 节"Prompt 工程的真实效果"声称的具体证据，让评审可以直接对比 v15（旧 prompt）与 v16（新 prompt 含"不强行套战术名"规则 + 30+ 术语库）在相同输入回合上的输出差异。

## A.1 失误回合：从"硬套战术"到"客观描述"

### 案例 A.1.1  Q1 6:36 SGA 传球失误

**原始 PBP**: `S. Gilgeous-Alexander bad pass TURNOVER (1 TO)`

**v15 输出（旧 prompt，硬套"战术"）**：

> 本回合属于"传球失误"战术。SGA 在弧顶持球后试图传球，但被防守预判抢断…

**v16 输出（新 prompt，正确客观）**：

> 本回合是 S. Gilgeous-Alexander 的传球失误。他在弧顶持球试图传给切入的队友时，传球路线被湖人防守球员预判拦截，导致球权转换。失误原因可能是传球意图过于明显或防守轮转到位。

**对比说明**：v15 错误地将"失误"称为"战术"，让解说显得幼稚不专业。v16 在"严格禁止"规则下，正确写为"是 XX 的传球失误"，并合理推断失误原因。

### 案例 A.1.2  Q1 5:08 SGA 控球失误

**原始 PBP**: `S. Gilgeous-Alexander lost ball TURNOVER (2 TO)`

**v16 输出**：

> 本回合是 S. Gilgeous-Alexander 的失误。他在持球时被防守者干扰或自身运球失误导致丢球，属于**个人控球失误，无明确战术配合**。

**对比说明**：v16 显式承认"无明确战术配合"，体现了 prompt 工程中"宁可少说，不可错说"的原则。

## A.2 节末回合：从"装腔作势"到"实事求是"

### 案例 A.2.1  Q1 节末

**原始 PBP**: `Period 1 end - clock 00:00.00 - SCORE: OKC 35 LAL 28`

**v15 输出（模板填充，缺乏具体性）**：

> Q1 收尾时刻。这是球队进入下一节前的最后一次进攻或防守。具体战术选择取决于剩余时间与当前分差。

**v16 输出（LLM 利用真实分数生成）**：

> Q1 收尾时刻。雷霆以 35-28 领先湖人，首节结束，双方进入节间休息。

**对比说明**：v15 的模板填充虽然不算"幻觉"但极其空洞。v16 的 LLM 在新 prompt 下能利用实际分数生成具体描述。

## A.3 战术回合：从"通用名"到"专业术语"

### 案例 A.3.1  Q1 10:30 Holmgren 助攻 Dort 三分

**原始 PBP**: `L. Dort 25' 3PT (3 PTS) (C. Holmgren 1 AST)`

**v16 输出**：

> 本回合属于『一五挡拆』(1-5 PnR) 战术。Holmgren 上提为 SGA 做掩护，吸引湖人防守收缩后，SGA 将球传给外弹的 Holmgren，后者迅速转移给弱侧空位的 Dort，创造三分机会。

**对比说明**：v16 在新增的 30+ 篮球术语库支持下，能准确使用"一五挡拆 (1-5 PnR)"这类专业术语，而非泛化的"挡拆配合"。

### 案例 A.3.2  Q1 9:54 Holmgren 弱侧空切扣篮

**原始 PBP**: `C. Holmgren cutting DUNK (2 PTS) (A. Mitchell 1 AST)`

**v16 输出**：

> 本回合属于『弱侧空切』(Weak-side cutting) 战术。Mitchell 在弧顶持球吸引防守，Holmgren 从弱侧沿底线空切至篮下，接 Mitchell 传球完成扣篮。防守方未能及时协防，暴露出对无球切入的警惕不足。

## A.4 v16 仍存在的失败案例（5/42 unsupported）

如第 5.5.5 节所述，v16 在 42 个 segment 中仍有 5 个被独立判官判定为 unsupported。这里展示典型的失败模式。

### 案例 A.4.1  虚构跨回合得分（结果与 PBP 矛盾）

**生成内容**：
> 本回合属于『拉开挡拆』(Spread PnR) 战术。SGA 在弧顶持球，J. Williams 上提掩护后外弹至三分线，SGA 吸引包夹后分球，Williams 第一次出手被 LaRavia 封盖，**但 Williams 冲抢进攻篮板后二次出手命中**。关键三分命中，将分差扩大至 8 分…

**判官判定**：unsupported

**判官理由**：解说称 Williams 二次出手命中且分差扩大至 8 分，但证据显示其三分被盖后**仅抢到篮板，无后续得分或比分变化记录**。

**失败模式**：LLM 在叙事流畅度的诱惑下，编造了 PBP 中不存在的"二次得分"。这是典型的"叙事补全"幻觉。

### 案例 A.4.2  人员张冠李戴（Ayton 根本不在阵容中）

**生成内容**：
> 本回合属于『翼侧挡拆』(Wing PnR) 战术。L. James 在右侧翼位与 **D. Ayton** 打挡拆，吸引防守后分球给底角 Kennard…

**判官判定**：unsupported

**判官理由**：解说称 L. James 与 D. Ayton 打挡拆后助攻 Kennard，但证据显示**助攻者是 L. James 自己，且无 D. Ayton 参与挡拆的任何记录，Ayton 不在该回合阵容中**。

**失败模式**：LLM 凭"印象"补全了球员姓名（Ayton 是大众认知中常与 James 联动的球员），但实际该场比赛中 Ayton 并未上场。这是典型的"训练数据带来的实体记忆偏差"。

### 案例 A.4.3  失误归属错误

**生成内容**：
> 失误回合。**J. Williams 在持球过程中被对手抢断**，导致球权丢失。

**判官判定**：unsupported

**判官理由**：证据显示 **J. Williams 自己丢球失误**，同时有他的抢断记录，但解说称被对手抢断，与证据矛盾。

**失败模式**：LLM 将"主动失误"（lost ball）误解为"被动失球"（被抢断）。这两个事件在 PBP 中字段不同，但 LLM 在叙事中将其混淆。

## A.5 改进路径

这 5 个失败案例都指向第 6 章未来工作的 3 个明确改进方向：

1. **几何数据扩展**（解决案例 A.4.1 类问题）：将 Fact Store 扩展到包含球员位置、出手角度、防守者距离等几何数据，让 Writer 在生成具体动作描述时有真实依据，而非"叙事补全"。
2. **回合阵容验证**（解决案例 A.4.2 类问题）：在 Researcher 阶段强制注入"本回合在场 10 名球员"白名单，使 Fact Checker 能直接拦截阵容外球员的引用。
3. **PBP 字段消歧**（解决案例 A.4.3 类问题）：在 prompt 中显式区分 `lost_ball` / `bad_pass` / `stolen_by` 三类失误的差异，避免 LLM 将它们混为一谈。

\newpage

# 附录 B  关键代码模块清单

本附录列出本系统实现中关键模块的代码组织。完整代码托管于 GitHub 公开仓库（https://github.com/kenpnw/sports-content-agent）。

| 模块路径 | 行数 | 功能描述 |
|----------|------|---------|
| `ingestion/nba_live.py` | 800+ | NBA Live API 接入，包括 schedule、scoreboard、boxscore、PBP 端点封装 |
| `ingestion/nba_pbp_fetcher.py` | 300+ | PBP 数据获取与规范化 |
| `video_scout/video_time_mapper.py` | 700+ | OCR 时间映射，包括 ffmpeg 帧采样、EasyOCR 调用、分段线性插值 |
| `video_scout/scoreboard_visibility_detector.py` | 500+ | 记分牌可见性检测，OpenCV 模板匹配 + 平滑 |
| `video_scout/auto_roi_detector.py` | 200+ | ROI 自动标定（POC），Canny + 矩形轮廓 |
| `video_scout/play_segment_detector.py` | 600+ | 播放段检测与 snap，包括 normalize_event_position |
| `video_scout/possession_boundary_detector.py` | 700+ | PBP 回合边界识别，事件 → observation 规范化 |
| `video_scout/tactic_analyzer.py` | 1000+ | 5-Agent 协议运行时，4 阶段 LLM 调用 |
| `video_scout/demo_runner.py` | 2000+ | 端到端流水线编排器，整合所有模块 |
| `video_scout/extract_clip_frames.py` | 100+ | 关键帧抽取 |
| `video_scout/clip_overview_poster.py` | 200+ | 60 clip 拼图海报生成 |
| `social_packager/repurpose.py` | 600+ | 4 平台社交内容打包 |
| `evaluation/run_experiment.py` | 400+ | 三系统消融实验框架 |
| `evaluation/baselines.py` | 300+ | GPT-only 与 Highlight-only baseline 实现 |
| `evaluation/metrics.py` | 500+ | 事实准确率、幻觉率、句级溯源率等评估指标 |
| `webapp/app.py` | 400+ | Flask 后端，提供 /api/nba/recent_games 等端点 |
| `webapp/job_manager.py` | 300+ | 异步任务管理 |
| `webapp/templates/tactical_review.html` | 1800+ | React + Ant Design 评审界面 |
| `webapp/templates/index.html` | 400+ | 控制台首页 |

\newpage
