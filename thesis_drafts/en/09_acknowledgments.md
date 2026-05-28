# Acknowledgments

As three years of master's study draw to a close, I look back on a path marked by the support of mentors, family, and friends, and offer my sincerest gratitude here.

First, I thank my advisor, Professor [advisor name]. From research direction selection to thesis finalization, my advisor has guided me with rigorous academic discipline and an open intellectual stance. At a critical juncture in choosing the system's initial architecture direction, his methodological guidance to "first build a complete end-to-end system, then optimize specific modules" saved me from the trap of "premature optimization" and helped me balance engineering depth with research value.

I thank all fellow students of Lab [lab name]. In repeated group meetings, the sharp questions raised by labmates — "how do you quantify hallucination?", "why not just use GPT-4?", "why isn't alignment accuracy 100%?" — repeatedly pushed me to refine vague claims into clear engineering metrics. I thank [senior student] for sharing experience on RAG system design and [junior student] for assistance debugging the video processing pipeline.

I thank the broader open-source community and platform providers whose work underlies this thesis: the DeepSeek language model API, NBA Live public API, EasyOCR open-source library, OpenCV vision processing library, and many other foundational technologies. Completing this research in the open ecosystem of AIGC engineering deeply taught me what it means to "stand on the shoulders of giants."

I thank the Paradoox AI team for the high-quality technical questions and equally insightful feedback throughout my interview process. Several engineering decisions in this work — "reviewer roles should not be the same LLM as the writer," "Prompt Contract rather than Prompt Engineering" — were directly inspired by team conversations, helping me rise from "how to write a system that works" to "how to write a system that earns trust."

I thank my parents and family. Over the past three years, they have provided unconditional emotional support and material security, enabling my focus on study. I thank my partner [name] for the understanding and companionship throughout countless late-night debugging sessions, rewrites, and re-rewrites.

Finally, I thank the sport of NBA basketball — and the global community of players, coaches, commentators, and content creators that sustains its culture. It is this love for the sport that has carried me through long engineering debugging sessions with sustained enthusiasm. Each time my system correctly identifies a "Spain PnR" or a step-back three-pointer, the joy comes doubled — engineering, plus the sport itself.

I dedicate this thesis to everyone who pours passion into this sport, on and off the court.

[Author Name]\
[Month] [Year]\
[University City]

\newpage

# Appendix A  Key Code Module Inventory

This appendix lists key module organization of the system implementation. The full code is hosted publicly at https://github.com/kenpnw/sports-content-agent.

| Module Path | Lines | Functionality |
|-------------|-------|---------------|
| `ingestion/nba_live.py` | 800+ | NBA Live API ingestion: schedule, scoreboard, boxscore, PBP endpoint wrappers |
| `ingestion/nba_pbp_fetcher.py` | 300+ | PBP data fetching and normalization |
| `video_scout/video_time_mapper.py` | 700+ | OCR time mapping: ffmpeg frame sampling, EasyOCR calls, piecewise-linear interpolation |
| `video_scout/scoreboard_visibility_detector.py` | 500+ | Scoreboard visibility detection: OpenCV template matching + smoothing |
| `video_scout/auto_roi_detector.py` | 200+ | ROI auto-calibration (POC): Canny + rectangle contours |
| `video_scout/play_segment_detector.py` | 600+ | Play-segment detection and snap, including normalize_event_position |
| `video_scout/possession_boundary_detector.py` | 700+ | PBP possession boundary identification, event → observation normalization |
| `video_scout/tactic_analyzer.py` | 1000+ | 5-Agent protocol runtime, 4-stage LLM calls |
| `video_scout/demo_runner.py` | 2000+ | End-to-end pipeline orchestrator, integrating all modules |
| `video_scout/extract_clip_frames.py` | 100+ | Key-frame extraction |
| `video_scout/clip_overview_poster.py` | 200+ | 60-clip contact-sheet generation |
| `social_packager/repurpose.py` | 600+ | 4-platform social content packaging |
| `evaluation/run_experiment.py` | 400+ | Three-system ablation experiment framework |
| `evaluation/baselines.py` | 300+ | GPT-only and Highlight-only baseline implementations |
| `evaluation/metrics.py` | 500+ | Fact accuracy, hallucination rate, sentence-level trace rate metrics |
| `webapp/app.py` | 400+ | Flask backend providing /api/nba/recent_games etc. endpoints |
| `webapp/job_manager.py` | 300+ | Asynchronous task management |
| `webapp/templates/tactical_review.html` | 1800+ | React + Ant Design review interface |
| `webapp/templates/index.html` | 400+ | Console homepage |

\newpage
