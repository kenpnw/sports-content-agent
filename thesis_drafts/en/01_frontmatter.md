---
title: "A Multi-Modal Multi-Agent Supervision Framework for NBA Real-Time Content Generation"
author: "[Author Name]"
date: "June 2026"
documentclass: article
fontsize: 12pt
linestretch: 1.5
geometry: "margin=1in"
---

\thispagestyle{empty}

\begin{center}

\vspace*{2cm}

{\Large School Code: [code]\hfill Student ID: [id]}

\vspace{2cm}

{\Huge \bf Master's Thesis}

\vspace{1cm}

{\Large \bf A Multi-Modal Multi-Agent Supervision Framework\\for NBA Real-Time Content Generation}

\vspace{3cm}

\begin{tabular}{ll}
Author:           & [Author Name] \\
Advisor:          & Prof. [Advisor Name] \\
Degree Type:      & Master of Engineering \\
Major:            & [Major] \\
Research Area:    & AI-Generated Content \\
Defense Date:     & June 2026 \\
\end{tabular}

\vspace{3cm}

{\Large [University Name]}

{\Large [Year]}

\end{center}

\newpage

# Abstract

In recent years, large language models (LLMs) such as GPT, PaLM, LLaMA, Qwen, and DeepSeek have demonstrated remarkable capabilities in content generation, fueling AI-generated content (AIGC) applications across journalism, media, and e-commerce. Yet in the specific domain of sports content — where **factual precision, platform-specific style differentiation, and tight delivery windows** all matter simultaneously — naive LLM solutions face three critical challenges. First, **factual hallucination**, in which the model fabricates plausible-sounding but incorrect scores, player actions, or tactical labels in the absence of external grounding, can severely damage editorial credibility. Second, **multimodal alignment** is difficult because roughly 40% of a typical NBA broadcast consists of replays, slow-motion footage, and commercials, defeating naive linear time mapping between text commentary and video segments. Third, **invisible credibility** undermines the practical value of AI content in professional media settings: even high-quality AI output gives the end reader no way to distinguish data-grounded claims from model conjecture.

To address these challenges in the context of NBA post-game content generation, this thesis proposes and implements a **multi-modal multi-agent supervision framework** that balances factual controllability, multimodal alignment accuracy, and stylistic diversity. The main contributions are five-fold.

**First**, we propose a **Multi-Agent Supervision Protocol** organized around five roles — Selector, Researcher, Writer, Fact Checker, and Risk Guard — each with explicit responsibility boundaries and output contracts. Unlike multi-agent debate frameworks that rely on adversarial collaboration to refine reasoning, our protocol introduces two reviewer roles (Fact Checker and Risk Guard) with hard blocking authority, requiring every pre-publication payload to clear both factual verification and risk audit gates. The protocol is accompanied by a formal **Prompt Contract** specification language that declares, for every LLM invocation, its task, source scope, evidence requirements, forbidden behaviors, output shape, and downstream review gates, rendering each agent's behavior boundary formal and auditable.

**Second**, we propose a **Dual-Layer Knowledge Architecture** that separates structured facts (a SQLite-backed Fact Store) from narrative text (a vector-indexed Text RAG store), with a routing policy ensuring that numeric assertions must be backed by the Fact Store, narrative framing may be drawn from Text RAG, and hybrid assertions prefer hard data over narrative interpretation. The architecture significantly improves numeric correctness over single-store vector RAG baselines.

**Third**, we propose a **visual frame-level clip alignment** scheme combining OCR-based time mapping with scoreboard-visibility detection. By using OpenCV template matching on per-second video frames, we obtain a play-segments curve spanning the entire game; combined with piecewise-linear interpolation over OCR samples, every play-by-play event is mapped to its true broadcast moment, avoiding clips falling on replays, slow-motion footage, or commercials. On the Oklahoma City Thunder vs. Los Angeles Lakers 2025 Playoffs G1, this scheme improves clip alignment accuracy from a baseline of 18% (naive linear mapping) to 83% (final pipeline).

**Fourth**, we propose **provenance-aware generation with visual verification**: each generated sentence is annotated with one of three factual-grounding states (verified / partial / unsupported) and surfaced to the end reader through a color-coded interface. This transforms otherwise invisible engineering metrics into a user-visible product feature, bridging *engineering-level trust* and *user-level trust*.

**Fifth**, we present an end-to-end system implementation and multi-dimensional evaluation. The system, comprising roughly 7,000 lines of Python, integrates NBA Live API ingestion, video time mapping, scoreboard visibility detection, clip extraction, five-agent orchestration, four-platform content packaging (Hupu, Douyin, Weibo, Xiaohongshu), and a React + Ant Design web review interface. In a three-system ablation study on a hand-annotated gold set, our pipeline achieves **73% Claim Coverage** of gold-annotated factual content (vs. 10% for GPT-only and 40% for Highlight-only) and **100% sentence-level evidence trace coverage** (vs. 18% and 61%), while maintaining 89% Claim Accuracy — a more useful engineering trade-off than the baselines' "silence-for-precision" 100% accuracy at 7.3× higher coverage. On the OKC vs. LAL G1 case study, **prompt-engineering iteration (v15 → v16) reduced the independent-judge hallucination rate from 33.3% to 11.9%**, a 64% relative reduction that places the system at the lower end of the RAG-based literature range. End-to-end clip alignment accuracy reaches 83% across 60 key possessions, and the generated four-platform content package covers all major distribution channels for Chinese-language post-game basketball content.

The engineering value of this work lies in providing reusable infrastructure for trustworthy content production, capable of compressing the end-to-end time from raw material to publishable multi-platform content from hours to minutes. The academic value lies in providing an end-to-end implemented and quantitatively evaluated work sample at the intersection of three active research lines: trustworthy LLM generation, retrieval-augmented generation, and multi-agent LLM systems.

**Keywords**: Large Language Model; Retrieval-Augmented Generation; Multi-Agent System; Sports Content Generation; Multimodal Alignment; Fact Provenance; Hallucination Suppression

\newpage

# Table of Contents

> *This page will be regenerated automatically in the final Word layout. The following top-level chapter list is a placeholder.*

- Chapter 1  Introduction
- Chapter 2  Related Work
- Chapter 3  System Design
- Chapter 4  Key Technical Implementation
- Chapter 5  Experiments and Evaluation
- Chapter 6  Conclusion and Future Work
- References
- Acknowledgments
- Appendix A  Key Code Module Inventory

\newpage
