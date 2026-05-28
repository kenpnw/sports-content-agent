---
title: "面向 NBA 实时内容生成的多模态多智能体监督框架"
subtitle: "A Multi-Modal Multi-Agent Supervision Framework for NBA Real-Time Content Generation"
author: "[作者姓名]"
date: "2026 年 6 月"
documentclass: article
fontsize: 12pt
linestretch: 1.5
geometry: "margin=1in"
---

\thispagestyle{empty}

\begin{center}

\vspace*{2cm}

{\Large 学校代码：[学校代码]\hfill 学  号：[学号]}

\vspace{2cm}

{\Huge \bf 硕士学位论文}

\vspace{1cm}

{\Large \bf 面向 NBA 实时内容生成的\\多模态多智能体监督框架}

\vspace{0.5cm}

{\large \it A Multi-Modal Multi-Agent Supervision Framework\\for NBA Real-Time Content Generation}

\vspace{3cm}

\begin{tabular}{ll}
作\ \ \ \ 者：& [作者姓名] \\
导\ \ \ \ 师：& [导师姓名] \ \ 教授 \\
学位类型：& 工程硕士 \\
专\ \ \ \ 业：& [专业名称] \\
研究方向：& 人工智能内容生成 \\
答辩日期：& 2026 年 [月] \\
\end{tabular}

\vspace{3cm}

{\Large [学校名称]}

{\Large [Year]}

\end{center}

\newpage

# 摘 要

近年来，以 GPT、PaLM、LLaMA、Qwen、DeepSeek 为代表的大语言模型在内容生成任务上展示出强大的能力，催生了 AIGC 在新闻、媒体、电商等多个领域的应用。然而在体育这一**事实精确性要求高、平台风格分化、且需在有限时间内交付**的特殊内容场景中，纯大语言模型方案普遍面临三类挑战：(1) 事实幻觉——模型在缺乏外部知识约束时生成看似合理但实则错误的比分、球员动作、战术名称等关键信息；(2) 多模态对齐困难——比赛全程录像中约有 40% 的画面是回放、慢镜头与商业广告，传统线性时间映射难以将文本评论与正确的视频时刻对齐；(3) 可信度不可见——即使生成内容质量达标，终端用户也无法判断哪些表述是基于真实数据、哪些是模型推断，削弱了 AI 内容在专业媒体场景中的可用性。

本研究面向 NBA 赛后内容生成场景，提出并实现了一套兼顾事实可控性、多模态对齐准确性与生成多样性的多模态多智能体监督框架。本研究的主要工作与贡献包括：

第一，提出"多智能体监督协议"——由 Selector、Researcher、Writer、Fact Checker、Risk Guard 五个角色组成的协同框架，每个角色拥有清晰的职责边界与输出契约。区别于以辩论协作为主的多智能体路线，本协议引入两个具有阻塞权的评审角色（Fact Checker 与 Risk Guard），使每个发布前的内容必须通过事实校验与风险审查双重门控。配套提出形式化"提示契约（Prompt Contract）"语言，将每个 LLM 调用的任务、证据范围、禁止行为、输出形态、评审网关等约束显式声明，使每个角色的行为边界可形式化、可审计。

第二，提出"双层知识架构"——针对体育领域"硬数据 + 软叙事"并存的特点，将知识存储与检索拆分为结构化事实库（Fact Store，基于 SQLite）与叙事文本库（Text RAG，基于向量索引）两层。配套的路由规则保证：数值类断言必须由 Fact Store 支撑；叙事框架可由 Text RAG 提供；混合断言中硬数据优先。该架构相比传统单一向量 RAG 在数值正确率上有显著提升。

第三，提出"OCR 时间映射 + 记分牌可见性检测"的视觉级片段对齐方案——利用 OpenCV 模板匹配在每秒视频帧上检测记分牌是否可见，得到一条贯穿全场的"播放段（play segments）"曲线；结合从 OCR 采样得到的"视频秒数 ↔ 比赛时钟"分段线性插值，将每个 PBP 事件准确映射到真实比赛画面，避免片段落在回放、慢镜头或广告上。本方案在 OKC 雷霆 vs 洛杉矶湖人 2025 年季后赛 G1 上将片段对齐准确率从基础线性映射的 18% 提升到最终方案的 83%。

第四，提出"可视化事实溯源"——在生成内容的句子粒度上标注事实归属状态，分为已验证、部分支持、未支持三态，将原本不可见的工程指标转化为终端用户可见的产品功能，是连接"工程级可信"与"用户级可信"之间的关键桥梁。

第五，端到端系统实现与多维度评估。系统在一个 7000 行代码的 Python 工程中实现，包括 NBA Live 接入、视频时间映射、记分牌可见性检测、片段提取、五智能体协同、四平台内容打包（虎扑、抖音、微博、小红书）与基于 React + Ant Design 的网页评审界面。在三系统消融实验中，本方案在金标注事实的**声明覆盖率**上达到 73%（vs GPT-only 10%、Highlight-only 40%）、**句级证据溯源率**达到 100%（vs 18% / 61%），同时声明准确率保持在 89%——相比 baseline"沉默换准确"的 100%，这是一个在 7.3 倍 Coverage 上仍维持高质量的、工程上更有用的权衡。在 OKC vs LAL G1 案例研究上，通过 Prompt 工程迭代（v15 → v16）将独立事实判官评估的**幻觉率从 33.3% 压降到 11.9%**（降幅 64%），处于文献中 RAG-based 系统的下沿区间。端到端流水线对 60 个关键回合的视频片段对齐准确率达到 83%，生成的 4 平台内容包覆盖了赛后传播的主要平台。

本研究的工程价值在于提供了一套可复用的可信内容生产基础设施，可压缩单场比赛从素材到 4 平台成稿的时间。本研究的学术价值在于在大语言模型可信生成、检索增强生成、多智能体协同三条研究线的交叉点上提供了一个有完整端到端实现与可量化评估的工作样本。

**关键词**：大语言模型；检索增强生成；多智能体系统；体育内容生成；多模态对齐；事实溯源；幻觉抑制

\newpage

# Abstract

In recent years, large language models (LLMs) such as GPT, PaLM, LLaMA, Qwen, and DeepSeek have demonstrated remarkable capabilities in content generation, fueling AI-generated content (AIGC) applications across journalism, media, and e-commerce. Yet in the specific domain of sports content — where **factual precision, platform-specific style differentiation, and tight delivery windows** all matter simultaneously — naive LLM solutions face three critical challenges: (1) **factual hallucination**, in which the model fabricates plausible-sounding but incorrect scores, player actions, or tactical labels in the absence of external grounding; (2) **multimodal alignment difficulty**, since roughly 40% of a typical NBA broadcast consists of replays, slow motion, and commercials, defeating naive linear time mapping between text commentary and video segments; and (3) **invisible credibility**, where even high-quality AI output gives the end reader no way to distinguish data-grounded claims from model conjecture, undermining the practical value of AI content in professional media settings.

To address these challenges in the context of NBA post-game content generation, this thesis proposes and implements a multi-modal multi-agent supervision framework that balances factual controllability, multimodal alignment accuracy, and stylistic diversity. The main contributions are:

**First**, we propose a **Multi-Agent Supervision Protocol** organized around five roles — Selector, Researcher, Writer, Fact Checker, and Risk Guard — each with explicit responsibility boundaries and output contracts. Unlike multi-agent debate frameworks that rely on adversarial collaboration, our protocol introduces two reviewer roles (Fact Checker and Risk Guard) with hard blocking authority, requiring every pre-publication payload to clear both factual verification and risk audit gates. The protocol is accompanied by a formal **Prompt Contract** specification language that declares, for every LLM invocation, its task, source scope, evidence requirements, forbidden behaviors, output shape, and downstream review gates, rendering each agent's behavior boundary formal and auditable.

**Second**, we propose a **Dual-Layer Knowledge Architecture** that separates structured facts (a SQLite-backed Fact Store) from narrative text (a vector-indexed Text RAG), with a routing rule ensuring that numeric assertions must be backed by the Fact Store, narrative framing may be drawn from Text RAG, and hybrid assertions prefer hard data. The architecture significantly improves numeric correctness over single-store vector RAG baselines.

**Third**, we propose a **visual frame-level clip alignment** scheme combining OCR-based time mapping with scoreboard-visibility detection. By using OpenCV template matching on per-second video frames, we obtain a play-segments curve spanning the entire game; combined with piece-wise linear interpolation over OCR samples, every play-by-play event is mapped to its true broadcast moment, avoiding clips falling on replays, slow motion, or commercials. On the OKC Thunder vs. Los Angeles Lakers 2025 Playoffs G1, this scheme improves clip alignment accuracy from a baseline of 18% (naive linear mapping) to 83% (final pipeline).

**Fourth**, we propose **provenance-aware generation with visual verification**: each generated sentence is annotated with one of three factual-grounding states (verified / partial / unsupported) and surfaced to the end reader. This transforms otherwise invisible engineering metrics into a user-visible product feature, bridging *engineering-level trust* and *user-level trust*.

**Fifth**, we present an end-to-end system implementation and multi-dimensional evaluation. The system, comprising roughly 7,000 lines of Python, integrates NBA Live API ingestion, video time mapping, scoreboard visibility detection, clip extraction, five-agent orchestration, four-platform content packaging (Hupu, Douyin, Weibo, Xiaohongshu), and a React + Ant Design web review interface. In a three-system ablation study on a hand-annotated gold set, our pipeline achieves **73% Claim Coverage** of gold-annotated factual content (vs. 10% for GPT-only and 40% for Highlight-only) and **100% sentence-level evidence trace coverage** (vs. 18% and 61%), while maintaining 89% Claim Accuracy — a more useful engineering trade-off than the baselines' "silence-for-precision" 100% accuracy at 7.3× higher coverage. On the OKC vs. LAL G1 case study, **prompt-engineering iteration (v15 → v16) reduced the independent-judge hallucination rate from 33.3% to 11.9%**, a 64% relative reduction placing the system at the lower end of the RAG-based literature range. End-to-end clip alignment accuracy reaches 83% across 60 key possessions, and the generated four-platform content package covers all major distribution channels for post-game basketball content in China.

The engineering value of this work lies in providing reusable infrastructure for trustworthy content production, capable of compressing the time from raw material to publishable four-platform content from hours to minutes. The academic value lies in providing an end-to-end implemented and quantitatively evaluated work sample at the intersection of three research lines: trustworthy LLM generation, retrieval-augmented generation, and multi-agent systems.

**Keywords**: Large Language Model; Retrieval-Augmented Generation; Multi-Agent System; Sports Content Generation; Multimodal Alignment; Fact Provenance; Hallucination Suppression

\newpage

# 目  录

> 此页面在最终排版时由 Word 自动生成。占位提示：以下列出 6 章主目录结构。

- 第 1 章  绪论
- 第 2 章  相关工作
- 第 3 章  系统设计
- 第 4 章  关键技术实现
- 第 5 章  实验与评估
- 第 6 章  总结与展望
- 参考文献
- 致谢
- 附录 A  关键代码模块清单

\newpage
