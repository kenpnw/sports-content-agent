"""End-to-end replay demo runner for the realtime commentary pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from realtime.event_detector import EventDetector
from realtime.live_commentator import LiveCommentator
from realtime.replay_simulator import PlayByPlayReplayer
from storage.file_store import ensure_dir, timestamp_slug, write_json, write_text


def run_replay_demo(
    replay_path: str,
    *,
    style: str = "hupu",
    speed: float = 10.0,
    sleep: bool = False,
    use_llm: bool = False,
    output_root: str | None = None,
) -> dict[str, Any]:
    replayer = PlayByPlayReplayer.from_file(replay_path, speed=speed)
    detector = EventDetector()
    commentator = LiveCommentator(default_style=style, enable_llm=use_llm)

    transcript: list[dict[str, Any]] = []
    last_emit_at: float | None = None

    for event, t_offset in replayer.stream(sleep=sleep):
        detected = detector.detect(event)
        if not commentator.should_emit(
            detected,
            last_commentary_at_seconds=last_emit_at,
            produced_at_seconds=t_offset,
        ):
            continue
        commentary = commentator.generate_commentary(
            detected,
            produced_at_seconds=t_offset,
            style=style,
        )
        last_emit_at = t_offset
        transcript.append(
            {
                "t_offset": round(t_offset, 2),
                "category": detected.category,
                "salience": round(detected.salience, 2),
                "clock": event.clock,
                "period": event.period,
                "score": {"home": event.home_score, "away": event.away_score},
                "event": event.description,
                "commentary": commentary.raw_text,
                "provenance": [
                    {
                        "text": tag.text,
                        "state": tag.state,
                        "confidence": tag.confidence,
                        "evidence_count": len(tag.evidence),
                    }
                    for tag in commentary.provenance
                ],
                "metadata": commentary.metadata,
            }
        )

    output_base = Path(output_root) if output_root else Path("data") / "generated" / "realtime_demo" / timestamp_slug()
    ensure_dir(output_base)
    write_json(output_base / "transcript.json", transcript)
    write_text(output_base / "transcript.md", _render_markdown(transcript, replay_path, style))

    return {
        "replay_path": replay_path,
        "style": style,
        "speed": speed,
        "sleep": sleep,
        "use_llm": use_llm,
        "event_count": replayer.metadata.event_count,
        "commentary_count": len(transcript),
        "output_dir": str(output_base.resolve()),
    }


def _render_markdown(transcript: list[dict[str, Any]], replay_path: str, style: str) -> str:
    lines = [
        "# Realtime Commentary Demo",
        "",
        f"- Replay: `{replay_path}`",
        f"- Style: `{style}`",
        f"- Commentary count: `{len(transcript)}`",
        "",
    ]
    for item in transcript:
        lines.extend(
            [
                f"## Q{item['period']} {item['clock']} | {item['score']['home']}-{item['score']['away']}",
                "",
                f"- Category: `{item['category']}`",
                f"- Event: {item['event']}",
                f"- Commentary: {item['commentary']}",
                "- Provenance:",
            ]
        )
        for tag in item["provenance"]:
            lines.append(
                f"  - `{tag['state']}` | confidence={tag['confidence']:.2f} | {tag['text']}"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the realtime replay demo pipeline.")
    parser.add_argument("--replay", required=True, help="Path to a replay JSON file.")
    parser.add_argument("--style", default="hupu", choices=["hupu", "douyin", "academic"])
    parser.add_argument("--speed", type=float, default=10.0, help="Replay speed multiplier.")
    parser.add_argument("--sleep", action="store_true", help="Sleep between replay events.")
    parser.add_argument("--use-llm", action="store_true", help="Use DeepSeek instead of deterministic fallback.")
    parser.add_argument("--output-dir", default="", help="Optional output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_replay_demo(
        args.replay,
        style=args.style,
        speed=args.speed,
        sleep=args.sleep,
        use_llm=args.use_llm,
        output_root=args.output_dir or None,
    )
    print(summary)


if __name__ == "__main__":
    main()
