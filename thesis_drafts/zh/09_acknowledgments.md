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

# 附录 A  关键代码模块清单

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
