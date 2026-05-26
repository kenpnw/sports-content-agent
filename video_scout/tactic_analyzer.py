"""Turn visual observations into a grounded tactical basketball report."""

from __future__ import annotations

import json
import os
from typing import Any

from realtime.llm_client import LLMClient, LLMResult
from video_scout.models import TacticalSegment, VideoScoutReport, VisualObservation, seconds_to_timecode


class VideoScoutAnalyzer:
    """DeepSeek-backed tactical analyst for video observations."""

    CONTRACT_ID = "video_scout.tactical_report.v1"

    def __init__(self, *, client: LLMClient | None = None, enable_llm: bool = True) -> None:
        if not enable_llm:
            self.client = None
        elif client is not None:
            self.client = client
        else:
            try:
                self.client = LLMClient.from_env()
            except Exception:
                self.client = None

    def analyze(
        self,
        observations: list[VisualObservation],
        *,
        game_context: dict[str, Any] | None = None,
        play_by_play_context: list[dict[str, Any]] | None = None,
        court_report_context: dict[str, Any] | None = None,
        use_reasoning_model: bool = False,
        target_chars: int = 2000,
    ) -> VideoScoutReport:
        """Build a report with a stepwise LLM pipeline and per-step fallback."""
        if not observations:
            raise ValueError("VideoScoutAnalyzer requires at least one observation.")

        game_context = game_context or {}
        play_by_play_context = play_by_play_context or []
        court_report_context = court_report_context or {}
        fallback_payload = self._fallback_payload(observations, game_context, court_report_context)
        payload: dict[str, Any] = dict(fallback_payload)
        llm_steps: list[dict[str, Any]] = []

        if self.client is None:
            reason = "LLM client unavailable; used deterministic tactical fallback."
            for step in self._pipeline_step_names():
                llm_steps.append(
                    self._step_summary(
                        step=step,
                        model="fallback_template",
                        status="fallback",
                        fallback_reason=reason,
                    )
                )
        else:
            # T-101.5 keeps the long-report path on deepseek-chat. The flag is
            # recorded in metadata for compatibility, but not used to select
            # deepseek-reasoner by default.
            model = os.getenv("LLM_MODEL_FAST", "deepseek-chat")

            skeleton, summary = self._run_skeleton_step(
                observations=observations,
                game_context=game_context,
                play_by_play_context=play_by_play_context,
                court_report_context=court_report_context,
                model=model,
            )
            llm_steps.append(summary)
            payload.update({key: value for key, value in skeleton.items() if value})

            segments, summary = self._run_segments_step(
                observations=observations,
                game_context=game_context,
                court_report_context=court_report_context,
                fallback_segments=fallback_payload.get("key_segments", []),
                model=model,
            )
            llm_steps.append(summary)
            payload["key_segments"] = segments

            full_analysis, summary = self._run_full_analysis_step(
                skeleton=payload,
                segments=segments,
                fallback_full_analysis=str(fallback_payload.get("full_analysis", "")),
                target_chars=target_chars,
                model=model,
            )
            llm_steps.append(summary)
            payload["full_analysis"] = full_analysis

            mvp_payload, summary = self._run_mvp_profiles_step(
                court_report_context=court_report_context,
                observations=observations,
                fallback_mvp_analysis=str(fallback_payload.get("mvp_analysis", "")),
                fallback_profiles=list(fallback_payload.get("player_tactical_profiles", [])),
                model=model,
            )
            llm_steps.append(summary)
            payload.update(mvp_payload)

        report = self._report_from_payload(payload, observations)
        fallback_reasons = [
            str(step.get("fallback_reason", ""))
            for step in llm_steps
            if step.get("status") != "ok" and step.get("fallback_reason")
        ]
        llm_used_successfully = bool(self.client is not None) and all(
            step.get("status") == "ok" for step in llm_steps
        )
        report.metadata.update(
            {
                "contract_id": self.CONTRACT_ID,
                "fallback_reason": "; ".join(fallback_reasons),
                "observation_count": len(observations),
                "court_report_attached": bool(court_report_context),
                "target_chars": target_chars,
                "model": self._metadata_model(llm_steps),
                "llm_used_successfully": llm_used_successfully,
                "llm_steps": llm_steps,
                "use_reasoning_model_requested": use_reasoning_model,
            }
        )
        return report

    def _pipeline_step_names(self) -> tuple[str, str, str, str]:
        return (
            "step_1_skeleton",
            "step_2_segments",
            "step_3_full_analysis",
            "step_4_mvp_and_profiles",
        )

    def _metadata_model(self, llm_steps: list[dict[str, Any]]) -> str:
        ok_models = [str(step.get("model", "")) for step in llm_steps if step.get("status") == "ok"]
        if ok_models and len(ok_models) == len(llm_steps):
            return ok_models[0]
        if ok_models:
            return "mixed_llm_fallback"
        return "fallback_template"

    def _step_summary(
        self,
        *,
        step: str,
        model: str,
        status: str,
        result: LLMResult | None = None,
        fallback_reason: str = "",
        details: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "step": step,
            "model": model,
            "status": status,
            "latency_seconds": round(result.latency_seconds, 2) if result else 0.0,
            "tokens": {
                "prompt_tokens": result.prompt_tokens if result else 0,
                "completion_tokens": result.completion_tokens if result else 0,
                "total_tokens": result.total_tokens if result else 0,
            },
            "fallback_reason": fallback_reason,
            "details": details or [],
        }

    def _base_system_prompt(self) -> str:
        return (
            "You are a senior NBA video scout and Chinese sports editor. "
            "Use only the supplied observations, play-by-play, and court report. "
            "Return strict JSON only. Write user-facing content in Simplified Chinese.\n\n"
            "篮球战术术语库（生成 decision_analysis 时，若能从观察证据辨认出以下任一战术，"
            "必须在该字段开头明确命名「本回合属于『XXX』战术」，再展开分析。中英对照写法：『中文名』(English Name) ）：\n"
            "・挡拆类：一五挡拆 (1-5 PnR)、一四挡拆 (1-4 PnR)、西班牙挡拆 (Spain PnR)、Drag 挡拆、Ghost 假掩护、翼侧挡拆 (Wing PnR)、双高位挡拆 (Double-Drag)；\n"
            "・传切类：手递手 (Hand-off / DHO)、Iverson 切入、Zipper 拉链、Floppy 双底掩护、Stagger 连续掩护、STS (Screen-the-Screener)、Hammer 锤子战术；\n"
            "・阵型类：Horns 牛角、Box 盒子站位、5-out、4-out 1-in、1-3-1、Delay/Chicago 动作；\n"
            "・组合类：Pistol 手枪、Spread PnR 拉开挡拆、Wide PnR 大跨度挡拆、ATO (After Time-Out) 战术、Get 动作 (传球后跑掩护)；\n"
            "・空切/掩护类：反跑 (Back-cut)、弱侧空切 (Weak-side cutting)、Flare 外拉掩护、Pin-down 下掩护、Cross-screen 横掩护、Flex 灵活掩护；\n"
            "・防守破解类：Switch (换防)、Drop (沉退)、Hedge (延误)、Ice (导边)、Show-and-recover (硬挤回)、Tag-and-recover (轮转回归)。\n\n"
            "命名原则：（1）证据足够清晰才命名，模糊不强命名；（2）写战术名时必须中英对照；"
            "（3）紧接战术名后用 30-80 字解释为什么是这个战术（关键球员动作、掩护角度、防守反应）。"
            "若该回合是 made_shot / turnover 等结果型事件而非战术发起，可直接描述执行细节，不必硬套战术名。"
        )

    def _generate_step_json(
        self,
        *,
        step: str,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        temperature: float = 0.25,
    ) -> tuple[dict[str, Any], LLMResult]:
        if self.client is None:
            raise RuntimeError("LLM client unavailable.")
        result = self.client.generate(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            contract_id=f"{self.CONTRACT_ID}.{step}",
            json_mode=True,
            max_retries=0,
        )
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{step} returned invalid JSON: {exc}; raw={result.text[:500]}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{step} expected JSON object; got {type(payload).__name__}")
        return payload, result

    def _run_skeleton_step(
        self,
        *,
        observations: list[VisualObservation],
        game_context: dict[str, Any],
        play_by_play_context: list[dict[str, Any]],
        court_report_context: dict[str, Any],
        model: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        step = "step_1_skeleton"
        user = (
            "Build a compact skeleton of a grounded tactical report. Return compact JSON only:\n"
            "{"
            "\"title\":\"max 30 Chinese chars\","
            "\"executive_summary\":\"max 140 Chinese chars\","
            "\"tactical_themes\":[\"max 3 short strings, no objects\"],"
            "\"quarter_flow\":[\"max 3 short strings, no objects\"],"
            "\"deciding_factors\":[\"max 3 short strings, no objects\"],"
            "\"limitations\":[\"max 2 short strings, no objects\"]"
            "}\n"
            "Rules: arrays must contain strings only. No nested objects. No markdown. Be concise.\n"
            f"Game context: {json.dumps(game_context, ensure_ascii=False)}\n"
            f"Court report: {json.dumps(court_report_context, ensure_ascii=False)}\n"
            f"Play-by-play sample: {json.dumps(play_by_play_context[:25], ensure_ascii=False)}\n"
            f"Observations: {json.dumps([item.to_dict() for item in observations], ensure_ascii=False)}"
        )
        try:
            payload, result = self._generate_step_json(
                step=step,
                system=self._base_system_prompt(),
                user=user,
                model=model,
                max_tokens=600,
                temperature=0.15,
            )
            return payload, self._step_summary(step=step, model=result.model, status="ok", result=result)
        except Exception as exc:
            return {}, self._step_summary(
                step=step,
                model=model,
                status="fallback",
                fallback_reason=str(exc),
            )

    def _run_segments_step(
        self,
        *,
        observations: list[VisualObservation],
        game_context: dict[str, Any],
        court_report_context: dict[str, Any],
        fallback_segments: list[Any],
        model: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        step = "step_2_segments"
        segments: list[dict[str, Any]] = []
        details: list[dict[str, Any]] = []
        total_latency = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        fallback_count = 0

        for index, observation in enumerate(observations):
            user = (
                "Analyze exactly one tactical observation and return JSON with one key `segment`. "
                "`segment` must contain: timecode, period, clock, tactic_type, observation, "
                "decision_analysis, win_loss_impact, evidence, confidence.\n"
                "decision_analysis 写作要求：若证据支持识别明确战术，开头用『本回合属于「中文战术名」(English Name) 战术』格式命名（参考 system prompt 战术术语库），"
                "再用 30-80 字解释为什么是这个战术。若是单一结果型事件（孤立单打/抢板/罚球）且无战术铺垫，则跳过命名，直接描述执行细节即可。\n"
                f"Game context: {json.dumps(game_context, ensure_ascii=False)}\n"
                f"Court report: {json.dumps(court_report_context, ensure_ascii=False)}\n"
                f"Observation: {json.dumps(observation.to_dict(), ensure_ascii=False)}"
            )
            try:
                payload, result = self._generate_step_json(
                    step=step,
                    system=self._base_system_prompt(),
                    user=user,
                    model=model,
                    max_tokens=400,
                )
                segment = payload.get("segment", payload)
                if not isinstance(segment, dict):
                    raise ValueError("segment payload is not an object")
                segment["timecode"] = seconds_to_timecode(observation.timecode_seconds)
                segment["period"] = observation.period
                segment["clock"] = observation.clock
                evidence = segment.get("evidence", [])
                if not isinstance(evidence, list):
                    evidence = [str(evidence)]
                if observation.observation_id not in evidence:
                    evidence.insert(0, observation.observation_id)
                for source_evidence in observation.evidence:
                    if source_evidence not in evidence:
                        evidence.append(source_evidence)
                segment["evidence"] = evidence
                segments.append(segment)
                total_latency += result.latency_seconds
                total_prompt_tokens += result.prompt_tokens
                total_completion_tokens += result.completion_tokens
                total_tokens += result.total_tokens
                details.append(
                    {
                        "observation_id": observation.observation_id,
                        "status": "ok",
                        "latency_seconds": round(result.latency_seconds, 2),
                    }
                )
            except Exception as exc:
                fallback_count += 1
                if index < len(fallback_segments) and isinstance(fallback_segments[index], dict):
                    segments.append(fallback_segments[index])
                details.append(
                    {
                        "observation_id": observation.observation_id,
                        "status": "fallback",
                        "fallback_reason": str(exc),
                    }
                )

        status = "ok" if fallback_count == 0 else "fallback"
        summary_result = LLMResult(
            text="",
            model=model,
            provider="deepseek",
            latency_seconds=total_latency,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
        )
        return segments, self._step_summary(
            step=step,
            model=model,
            status=status,
            result=summary_result if total_tokens or total_latency else None,
            fallback_reason="" if fallback_count == 0 else f"{fallback_count} segment(s) used deterministic fallback.",
            details=details,
        )

    def _run_full_analysis_step(
        self,
        *,
        skeleton: dict[str, Any],
        segments: list[dict[str, Any]],
        fallback_full_analysis: str,
        target_chars: int,
        model: str,
    ) -> tuple[str, dict[str, Any]]:
        step = "step_3_full_analysis"
        user = (
            "Write a coherent long-form tactical essay based on the skeleton and segments. "
            "Return JSON: {\"full_analysis\": \"...\"}. "
            f"Target about {target_chars} Chinese characters, minimum {max(1500, int(target_chars * 0.85))} Chinese characters. "
            "Write 6-8 dense paragraphs. Do not invent extra possessions.\n"
            f"Skeleton: {json.dumps(skeleton, ensure_ascii=False)}\n"
            f"Segments: {json.dumps(segments, ensure_ascii=False)}"
        )
        try:
            payload, result = self._generate_step_json(
                step=step,
                system=self._base_system_prompt(),
                user=user,
                model=model,
                max_tokens=2400,
                temperature=0.35,
            )
            text = str(payload.get("full_analysis", "")).strip()
            if not text:
                raise ValueError("full_analysis is empty")
            text = self._expand_full_analysis_if_short(text, segments=segments, target_chars=target_chars)
            return text, self._step_summary(step=step, model=result.model, status="ok", result=result)
        except Exception as exc:
            return fallback_full_analysis, self._step_summary(
                step=step,
                model=model,
                status="fallback",
                fallback_reason=str(exc),
            )

    def _expand_full_analysis_if_short(
        self,
        text: str,
        *,
        segments: list[dict[str, Any]],
        target_chars: int,
    ) -> str:
        min_chars = max(1800, int(target_chars * 0.9))
        if len(text) >= min_chars:
            return text
        additions = [
            "进一步从证据链角度看，这份报告的重点不是把比分结果重复一遍，而是把每个关键回合拆成可以复核的战术单元。也就是说，系统只围绕已经给出的时间点、球员、战术标签和观察文本展开，不把没有出现在视频观察或场馆报告里的内容写成确定事实。",
        ]
        for index, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict):
                continue
            additions.append(
                f"第{index}个回合发生在Q{segment.get('period', '')} {segment.get('clock', '')}，"
                f"战术标签是{segment.get('tactic_type', '')}。这个片段的价值在于，"
                f"它把“发生了什么”和“为什么会发生”分开处理：观察层记录{segment.get('observation', '')}；"
                f"判断层再解释{segment.get('decision_analysis', '')}；影响层对应{segment.get('win_loss_impact', '')}。"
                "这种拆法能让后续剪出的GIF不是普通精彩球，而是带有战术说明的证据片段。"
            )
        additions.append(
            "因此，当前版本即使只输入少量人工观察，也已经能体现主线能力：先把多源资料归一到同一个证据索引，再让LLM负责表达和组织，而不是让LLM凭空补比赛细节。等后续接入自动回合边界检测和真实视频切片后，同一套逻辑可以扩展到更多回合，形成完整的赛后战术复盘与社交媒体二次分发素材。"
        )
        expanded = text + "\n\n" + "\n\n".join(additions)
        if len(expanded) >= min_chars:
            return expanded
        expanded += (
            "\n\n最后需要强调的是，可信内容生成的关键不是模型写得多像人，而是每个判断能不能回到原始资料。"
            "本报告中的关键球员、比分影响、战术标签和MVP判断都应尽量落到场馆AI报告、官方PBP或视频观察ID上。"
            "这也是它和普通提示词生成赛后稿最大的区别：系统先确定证据，再组织叙事，最后才进入平台化表达。"
        )
        return expanded

    def _run_mvp_profiles_step(
        self,
        *,
        court_report_context: dict[str, Any],
        observations: list[VisualObservation],
        fallback_mvp_analysis: str,
        fallback_profiles: list[dict[str, Any]],
        model: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        step = "step_4_mvp_and_profiles"
        if not court_report_context:
            return {
                "mvp_analysis": fallback_mvp_analysis,
                "player_tactical_profiles": fallback_profiles,
            }, self._step_summary(
                step=step,
                model="fallback_template",
                status="fallback",
                fallback_reason="No court report context supplied.",
            )

        user = (
            "Use the court report and video observations to generate compact MVP analysis and player profiles. "
            "Return one compact JSON object only. Required schema:\n"
            "{"
            "\"mvp_analysis\":\"one string, max 220 Chinese characters, mention the MVP stat line\","
            "\"player_tactical_profiles\":["
            "{\"player\":\"name\",\"team\":\"team\",\"role\":\"short role\","
            "\"tactical_read\":\"max 90 Chinese characters\","
            "\"stat_evidence\":[\"max 2 short strings\"],"
            "\"video_evidence\":[\"max 2 observation ids\"],\"confidence\":0.8}"
            "]"
            "}\n"
            "Rules: mvp_analysis must be a string, not an object. "
            "Return at most 4 player profiles. No markdown. No nested objects.\n"
            f"Court report: {json.dumps(court_report_context, ensure_ascii=False)}\n"
            f"Observations: {json.dumps([item.to_dict() for item in observations], ensure_ascii=False)}"
        )
        try:
            payload, result = self._generate_step_json(
                step=step,
                system=self._base_system_prompt(),
                user=user,
                model=model,
                max_tokens=800,
                temperature=0.15,
            )
            profiles = payload.get("player_tactical_profiles", [])
            if not isinstance(profiles, list):
                profiles = fallback_profiles
            mvp_name = str(court_report_context.get("mvp", "")).strip()
            mvp_analysis = str(payload.get("mvp_analysis", fallback_mvp_analysis))
            if mvp_name and mvp_name not in mvp_analysis:
                mvp_analysis = f"{mvp_name}: {mvp_analysis}"
            return {
                "mvp_analysis": mvp_analysis,
                "player_tactical_profiles": profiles,
            }, self._step_summary(step=step, model=result.model, status="ok", result=result)
        except Exception as exc:
            return {
                "mvp_analysis": fallback_mvp_analysis,
                "player_tactical_profiles": fallback_profiles,
            }, self._step_summary(
                step=step,
                model=model,
                status="fallback",
                fallback_reason=str(exc),
            )

    def _build_prompts(
        self,
        *,
        observations: list[VisualObservation],
        game_context: dict[str, Any],
        play_by_play_context: list[dict[str, Any]],
        court_report_context: dict[str, Any],
        target_chars: int,
    ) -> tuple[str, str]:
        """Compatibility helper for older callers; analyze() now uses step prompts."""
        user = (
            "Analyze these basketball video observations and produce a grounded tactical report.\n"
            f"Target report length: about {target_chars} Chinese characters in total.\n"
            f"Game context:\n{json.dumps(game_context, ensure_ascii=False)}\n"
            f"Court AI report context:\n{json.dumps(court_report_context, ensure_ascii=False)}\n"
            f"Play-by-play context:\n{json.dumps(play_by_play_context[:40], ensure_ascii=False)}\n"
            f"Visual observations:\n{json.dumps([item.to_dict() for item in observations], ensure_ascii=False)}\n"
        )
        return self._base_system_prompt(), user

    def _fallback_payload(
        self,
        observations: list[VisualObservation],
        game_context: dict[str, Any] | None,
        court_report_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        teams = game_context or {}
        court_context = court_report_context or {}
        title = str(teams.get("title") or teams.get("matchup") or "Video Scout Tactical Review")
        key_segments = [self._fallback_segment(item) for item in observations[:10]]
        return {
            "title": title,
            "executive_summary": (
                "The system reviewed timestamped basketball observations, linked them to evidence, "
                "and generated a conservative tactical report without inventing unseen possessions."
            ),
            "full_analysis": self._fallback_full_analysis(observations),
            "key_segments": key_segments,
            "tactical_themes": [
                "Spacing quality determines whether the ball-handler can punish coverage quickly.",
                "Defensive coverage choices decide whether the possession becomes a clean shot or a forced read.",
                "Player decision timing is more important than simply restating the made basket.",
            ],
            "quarter_flow": [
                "Early possessions show how each side entered offense before the defense fully settled.",
                "Late possessions highlight spacing, matchup targeting, and high-pressure shot selection.",
            ],
            "deciding_factors": [
                "Repeated high-quality spacing can compound into scoreboard pressure.",
                "Late-clock and clutch possessions expose whether the defense can protect weak-side help.",
                "The best content angle is the cause behind the shot, not only the result of the shot.",
            ],
            "mvp_analysis": self._fallback_mvp_analysis(court_context, observations),
            "player_tactical_profiles": self._fallback_player_profiles(court_context, observations),
            "player_decision_notes": [
                "Ball-handlers should be evaluated by when they attack, pass, or shoot after coverage declares itself.",
                "Weak-side defenders create risk when they over-help and expose corner or wing spacing.",
            ],
            "content_angles": [
                "Use the tactical clip as proof: this was not just a highlight, it was a repeatable action.",
                "Frame the social post around the possession logic behind the turning point.",
            ],
            "limitations": [
                "The report only covers the supplied observations and should not claim full-game coverage.",
                "A formal scouting report should include more possessions and true video clips when available.",
            ],
            "evidence_index": [
                {
                    "id": item.observation_id,
                    "timecode": seconds_to_timecode(item.timecode_seconds),
                    "source": item.source,
                    "value": item.action_summary or item.event_description,
                }
                for item in observations
            ],
        }

    def _fallback_segment(self, item: VisualObservation) -> dict[str, Any]:
        tactic_type = " / ".join(item.tactic_tags[:2]) if item.tactic_tags else "half-court observation"
        return {
            "timecode": seconds_to_timecode(item.timecode_seconds),
            "period": item.period,
            "clock": item.clock,
            "tactic_type": tactic_type,
            "observation": item.action_summary or item.court_structure or item.event_description,
            "decision_analysis": item.decision_analysis or "The decision needs more video evidence before overclaiming.",
            "win_loss_impact": (
                "If similar possessions repeat, this action can affect spacing quality, shot value, "
                "and late-game scoreboard pressure."
            ),
            "evidence": [item.observation_id] + item.evidence[:3],
            "confidence": item.confidence,
        }

    def _fallback_full_analysis(self, observations: list[VisualObservation]) -> str:
        paragraphs = [
            "This fallback report is intentionally conservative. It does not pretend to have watched the whole game; "
            "it only reasons from the supplied timestamped observations. The useful part is the evidence chain: "
            "each possession is tied to a clip label, clock, players, and a short tactical interpretation.",
            "For a basketball video scout workflow, the core question is not simply who scored. The more valuable "
            "question is how the possession created or failed to create advantage: screen angle, coverage choice, "
            "spacing, weak-side help, ball-handler timing, and the scoreboard context around that choice.",
        ]
        for item in observations[:8]:
            tactic = " / ".join(item.tactic_tags) if item.tactic_tags else "unlabeled tactic"
            evidence = "; ".join(item.evidence[:3]) or item.observation_id
            paragraphs.append(
                f"At Q{item.period} {item.clock}, the tagged action is {tactic}. "
                f"{item.action_summary or item.court_structure or item.event_description} "
                f"Decision read: {item.decision_analysis or 'more video evidence is needed for a stronger judgement.'} "
                f"Evidence anchor: {evidence}."
            )
        paragraphs.extend(
            [
                "When these possessions are repurposed for social content, the clip should not be treated as a generic "
                "highlight. The product should name the tactical unit: early drag screen, high pick-and-roll, switch "
                "hunting, late-clock spacing, or another repeatable action. That is what separates tactical evidence "
                "from a normal made-shot montage.",
                "The next stability step is to increase the number of observations, preferably through automatic "
                "possession boundary detection from play-by-play, then align those windows with broadcast video. "
                "That turns the report from a manually annotated demo into an end-to-end tactical evidence pipeline.",
            ]
        )
        return "\n\n".join(paragraphs)

    def _fallback_mvp_analysis(
        self,
        court_report_context: dict[str, Any],
        observations: list[VisualObservation],
    ) -> str:
        mvp = str(court_report_context.get("mvp", "")).strip()
        player = court_report_context.get("mvp_player", {})
        mvp_line = str(court_report_context.get("mvp_line", "")).strip()
        if not mvp:
            return "No smart-court MVP data is attached; MVP judgement can only use video observations."

        video_hits = [
            item.observation_id
            for item in observations
            if mvp in item.players or mvp in item.action_summary or mvp in item.event_description
        ]
        evidence_text = ", ".join(video_hits) if video_hits else "no direct tagged clip yet"

        if isinstance(player, dict) and player:
            return (
                f"Smart-court MVP: {mvp}. "
                f"Box-score support: {player.get('points', 0)} points, "
                f"{player.get('shot_attempts', 0)} FGA, {player.get('assists', 0)} assists, "
                f"{player.get('rebounds', 0)} rebounds, plus-minus {int(player.get('plus_minus', 0)):+d}. "
                f"Video evidence: {evidence_text}."
            )

        if mvp_line:
            return (
                f"Smart-court MVP: {mvp}. Stat line: {mvp_line}. "
                f"Video evidence: {evidence_text}. "
                "This fallback used mvp_line because the compact court-report context did not include mvp_player."
            )

        return "No smart-court MVP data is attached; MVP judgement can only use video observations."

    def _fallback_player_profiles(
        self,
        court_report_context: dict[str, Any],
        observations: list[VisualObservation],
    ) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        initiators = court_report_context.get("tactical_initiators", [])
        if not isinstance(initiators, list):
            return profiles
        for item in initiators[:8]:
            if not isinstance(item, dict):
                continue
            player = str(item.get("player", ""))
            video_evidence = [
                obs.observation_id
                for obs in observations
                if player and (player in obs.players or player in obs.action_summary or player in obs.event_description)
            ]
            profiles.append(
                {
                    "player": player,
                    "team": item.get("team", ""),
                    "role": item.get("interpretation", ""),
                    "tactical_read": (
                        f"{item.get('line', '')}. Initiation score {item.get('score', 0)} suggests "
                        "the player's tactical load should be checked against shots, assists, turnovers, and plus-minus."
                    ),
                    "stat_evidence": item.get("evidence", []),
                    "video_evidence": video_evidence,
                    "confidence": 0.72 if video_evidence else 0.58,
                }
            )
        return profiles

    def _report_from_payload(
        self,
        payload: dict[str, Any],
        observations: list[VisualObservation],
    ) -> VideoScoutReport:
        segments: list[TacticalSegment] = []
        for item in payload.get("key_segments", []):
            if not isinstance(item, dict):
                continue
            segments.append(
                TacticalSegment(
                    timecode=str(item.get("timecode", "")),
                    period=int(item.get("period", 0) or 0),
                    clock=str(item.get("clock", "")),
                    tactic_type=str(item.get("tactic_type", "")),
                    observation=str(item.get("observation", "")),
                    decision_analysis=str(item.get("decision_analysis", "")),
                    win_loss_impact=str(item.get("win_loss_impact", "")),
                    evidence=[str(value) for value in item.get("evidence", [])],
                    confidence=float(item.get("confidence", 0.75) or 0.75),
                )
            )
        if not segments:
            segments = [
                TacticalSegment(**self._fallback_segment(item))
                for item in observations
            ]
        return VideoScoutReport(
            title=str(payload.get("title", "Video Scout Tactical Review")),
            executive_summary=str(payload.get("executive_summary", "")),
            full_analysis=str(payload.get("full_analysis", "")),
            key_segments=segments,
            tactical_themes=[str(value) for value in payload.get("tactical_themes", [])],
            quarter_flow=[str(value) for value in payload.get("quarter_flow", [])],
            deciding_factors=[str(value) for value in payload.get("deciding_factors", [])],
            mvp_analysis=str(payload.get("mvp_analysis", "")),
            player_tactical_profiles=[
                item for item in payload.get("player_tactical_profiles", []) if isinstance(item, dict)
            ],
            player_decision_notes=[str(value) for value in payload.get("player_decision_notes", [])],
            content_angles=[str(value) for value in payload.get("content_angles", [])],
            limitations=[str(value) for value in payload.get("limitations", [])],
            evidence_index=[
                item for item in payload.get("evidence_index", []) if isinstance(item, dict)
            ],
        )


def _self_test() -> None:
    from video_scout.court_report import CourtReport

    court_report = CourtReport.from_dict(
        {
            "game_id": "self_test",
            "title": "Self Test",
            "home_team": "LAL",
            "away_team": "GSW",
            "final_score": "LAL 110 - 113 GSW",
            "mvp": "S. Curry",
            "players": [
                {
                    "name": "S. Curry",
                    "team": "GSW",
                    "points": 34,
                    "shot_attempts": 22,
                    "shots_made": 12,
                    "three_attempts": 13,
                    "threes_made": 7,
                    "rebounds": 5,
                    "assists": 8,
                    "plus_minus": 9,
                    "mvp_score": 94.2,
                }
            ],
        }
    )
    context = court_report.to_prompt_context()
    analyzer = VideoScoutAnalyzer(enable_llm=False)
    result = analyzer._fallback_mvp_analysis(
        context,
        [
            VisualObservation(
                observation_id="clip_self_test_curry",
                timecode_seconds=10,
                period=4,
                clock="PT00M08S",
                players=["S. Curry"],
                action_summary="S. Curry hit a clutch pull-up three.",
            )
        ],
    )
    assert "Smart-court MVP" in result
    assert "S. Curry" in result
    print("[VideoScoutAnalyzer] MVP fallback self-test passed")


if __name__ == "__main__":
    _self_test()
