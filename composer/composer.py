"""Composition module for assembling final social-ready content packages."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.table import Table

from artist.diagram_generator import DiagramGenerator
from artist.player_card import PlayerCard
from content_agent.strategy_engine import StrategyEngine
from reader.pdf_reader import PDFReader


class Composer:
    """Combines text and visual assets into platform-ready deliverables."""

    def __init__(self, output_dir: str) -> None:
        self.console = Console()
        self.output_dir = Path(output_dir)
        self.channels = ["hupu", "weibo", "xiaohongshu"]
        for channel in self.channels:
            (self.output_dir / channel).mkdir(parents=True, exist_ok=True)
        (self.output_dir / "_tmp").mkdir(parents=True, exist_ok=True)

        self.reader: PDFReader | None = None
        self.strategy_engine: StrategyEngine | None = None
        self.diagram_generator: DiagramGenerator | None = None
        self.player_card: PlayerCard | None = None
        self._init_modules()

    def _init_modules(self) -> None:
        try:
            self.strategy_engine = StrategyEngine()
        except Exception as exc:
            self.console.print(f"[red]初始化 StrategyEngine 失败: {exc}[/red]")
        try:
            self.diagram_generator = DiagramGenerator()
        except Exception as exc:
            self.console.print(f"[red]初始化 DiagramGenerator 失败: {exc}[/red]")
        try:
            self.player_card = PlayerCard()
        except Exception as exc:
            self.console.print(f"[red]初始化 PlayerCard 失败: {exc}[/red]")

    def _pick_player_data(self, report: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        players = report.get("players", [])
        first_player = players[0] if isinstance(players, list) and players else {}
        if not isinstance(first_player, dict):
            first_player = {}
        name = str(first_player.get("name", item.get("title", "球员解读"))).strip() or "球员解读"
        team = "未知球队"
        matchup_notes = report.get("matchup_notes", [])
        if isinstance(matchup_notes, list) and matchup_notes:
            first_note = matchup_notes[0]
            if isinstance(first_note, dict):
                team = str(first_note.get("team", team)).strip() or team
        stats = first_player.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        return {
            "name": name,
            "team": team,
            "stats": stats,
            "key_insight": str(item.get("caption", "")).strip() or "暂无关键信息",
            "comparison": str(item.get("hook", "")).strip(),
        }

    def _pick_tactic_data(self, report: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        tactics = report.get("tactics", [])
        first_tactic = tactics[0] if isinstance(tactics, list) and tactics else {}
        if not isinstance(first_tactic, dict):
            first_tactic = {}
        return {
            "name": str(item.get("title", first_tactic.get("name", "战术拆解"))).strip() or "战术拆解",
            "description": str(item.get("caption", first_tactic.get("description", ""))).strip(),
            "player_positions": first_tactic.get("player_positions", []),
            "movement_arrows": first_tactic.get("movement_arrows", []),
        }

    def _render_visual(
        self,
        platform: str,
        index: int,
        item: dict[str, Any],
        report: dict[str, Any],
    ) -> Path | None:
        tmp_path = self.output_dir / "_tmp" / f"{platform}_{index + 1}.png"
        content_type = str(item.get("content_type", "stat_infographic")).strip()
        badge = str(item.get("badge_suggestion", "稳")).strip()
        try:
            if content_type == "player_card" and self.player_card:
                player_payload = self._pick_player_data(report, item)
                return Path(self.player_card.create_player_card(player_payload, badge, str(tmp_path)))
            if content_type == "tactical_diagram" and self.diagram_generator:
                tactic_payload = self._pick_tactic_data(report, item)
                positions = tactic_payload.get("player_positions", [])
                arrows = tactic_payload.get("movement_arrows", [])
                has_positions = isinstance(positions, list) and len(positions) > 0
                has_arrows = isinstance(arrows, list) and len(arrows) > 0
                if has_positions or has_arrows:
                    return Path(
                        self.diagram_generator.create_tactical_diagram(
                            tactic_payload,
                            str(tmp_path),
                            badge=badge,
                        )
                    )
                return Path(
                    self.diagram_generator.create_simple_diagram(
                        tactic_payload.get("name", "战术图"),
                        tactic_payload.get("description", ""),
                        str(tmp_path),
                    )
                )
            if self.diagram_generator:
                title = str(item.get("title", "数据解读")).strip() or "数据解读"
                caption = str(item.get("caption", "")).strip()
                return Path(self.diagram_generator.create_simple_diagram(title, caption, str(tmp_path)))
            self.console.print(f"[yellow]{platform} 第{index + 1}条未生成图片：图像模块不可用[/yellow]")
            return None
        except Exception as exc:
            self.console.print(f"[red]{platform} 第{index + 1}条图片生成失败: {exc}[/red]")
            return None

    def run_pipeline(self, pdf_path: str) -> dict[str, Any]:
        report: dict[str, Any] = {"players": [], "tactics": [], "quotes": [], "matchup_notes": [], "page_count": 0}
        strategy: dict[str, Any] = {"angles": [], "platform_content": {p: [] for p in self.channels}}
        platform_folders: dict[str, str] = {}
        platform_visuals: dict[str, list[Path]] = {p: [] for p in self.channels}
        self.console.print(Panel("开始执行内容生产流水线", title="Sports Agent Composer"))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=self.console,
        ) as progress:
            task_id = progress.add_task("流水线执行中", total=4)

            try:
                self.reader = PDFReader(pdf_path)
                report = self.reader.extract_full_report()
            except Exception as exc:
                self.console.print(f"[red]Reader 阶段失败: {exc}[/red]")
            progress.update(task_id, advance=1, description="Reader 阶段完成")

            try:
                if not self.strategy_engine:
                    raise RuntimeError("StrategyEngine 未初始化")
                strategy = self.strategy_engine.generate_full_strategy(report)
            except Exception as exc:
                self.console.print(f"[red]Content Agent 阶段失败: {exc}[/red]")
            progress.update(task_id, advance=1, description="Content Agent 阶段完成")

            try:
                platform_content = strategy.get("platform_content", {})
                if not isinstance(platform_content, dict):
                    platform_content = {}
                for platform in self.channels:
                    content_items = platform_content.get(platform, [])
                    if not isinstance(content_items, list):
                        content_items = []
                    for idx, item in enumerate(content_items):
                        if not isinstance(item, dict):
                            continue
                        visual_path = self._render_visual(platform, idx, item, report)
                        if visual_path:
                            platform_visuals[platform].append(visual_path)
            except Exception as exc:
                self.console.print(f"[red]Artist 阶段失败: {exc}[/red]")
            progress.update(task_id, advance=1, description="Artist 阶段完成")

            try:
                platform_content = strategy.get("platform_content", {})
                if not isinstance(platform_content, dict):
                    platform_content = {}
                for platform in self.channels:
                    items = platform_content.get(platform, [])
                    if not isinstance(items, list):
                        items = []
                    folder = self.package_for_platform(platform, items, platform_visuals.get(platform, []))
                    platform_folders[platform] = folder
            except Exception as exc:
                self.console.print(f"[red]打包阶段失败: {exc}[/red]")
            progress.update(task_id, advance=1, description="打包阶段完成")

        summary = {
            "pdf_path": pdf_path,
            "pages_processed": int(report.get("page_count", 0) or 0),
            "angles_found": len(strategy.get("angles", [])) if isinstance(strategy.get("angles", []), list) else 0,
            "content_pieces": {
                platform: len(strategy.get("platform_content", {}).get(platform, []))
                if isinstance(strategy.get("platform_content", {}), dict)
                and isinstance(strategy.get("platform_content", {}).get(platform, []), list)
                else 0
                for platform in self.channels
            },
            "images_created": sum(len(paths) for paths in platform_visuals.values()),
            "output_folders": platform_folders,
        }
        self.generate_report_summary(summary)
        return summary

    def package_for_platform(
        self, platform: str, content_items: list[dict[str, Any]], visuals: list[Path]
    ) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = self.output_dir / platform / timestamp
        target_dir.mkdir(parents=True, exist_ok=True)

        copied_images: list[str] = []
        for idx, visual_path in enumerate(visuals):
            try:
                if not visual_path.exists():
                    continue
                image_name = f"{platform}_{idx + 1}.png"
                destination = target_dir / image_name
                shutil.copy2(visual_path, destination)
                copied_images.append(image_name)
            except Exception as exc:
                self.console.print(f"[red]{platform} 复制图片失败: {exc}[/red]")

        tips = self.generate_posting_tips(platform)
        first_item = content_items[0] if content_items else {}
        if not isinstance(first_item, dict):
            first_item = {}
        content_payload = {
            "platform": platform,
            "title": str(first_item.get("title", "")).strip(),
            "caption": str(first_item.get("caption", "")).strip(),
            "hashtags": first_item.get("hashtags", []) if isinstance(first_item.get("hashtags", []), list) else [],
            "image_count": len(copied_images),
            "posting_tips": tips,
        }
        (target_dir / "content.json").write_text(
            json.dumps(content_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        lines = [
            f"# {platform} 发布说明",
            "",
            f"标题：{content_payload['title']}",
            "",
            "文案：",
            content_payload["caption"],
            "",
            "标签：",
            " ".join(str(tag) for tag in content_payload["hashtags"]),
            "",
            "发布建议：",
        ]
        lines.extend([f"- {tip}" for tip in tips])
        lines.extend(["", "图片文件："])
        lines.extend([f"- {image}" for image in copied_images])
        (target_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
        return str(target_dir)

    def generate_posting_tips(self, platform: str) -> list[str]:
        tips_map = {
            "hupu": ["发布时间建议：晚8-10点", "配合热点话题标签", "首图用最强数据对比"],
            "weibo": ["用@大V扩散", "添加超话标签", "视频封面要有冲击力"],
            "xiaohongshu": ["标题带数字更吸量", "前3张图最关键", "评论区引导互动"],
        }
        return tips_map.get(platform, [])

    def generate_report_summary(self, summary: dict[str, Any]) -> None:
        table = Table(title="流水线执行汇总")
        table.add_column("指标", style="cyan")
        table.add_column("结果", style="magenta")
        table.add_row("处理页数", str(summary.get("pages_processed", 0)))
        table.add_row("角度数量", str(summary.get("angles_found", 0)))
        content_pieces = summary.get("content_pieces", {})
        if isinstance(content_pieces, dict):
            table.add_row("虎扑内容", str(content_pieces.get("hupu", 0)))
            table.add_row("微博内容", str(content_pieces.get("weibo", 0)))
            table.add_row("小红书内容", str(content_pieces.get("xiaohongshu", 0)))
        table.add_row("图片总数", str(summary.get("images_created", 0)))
        self.console.print(table)

    def main(self, pdf_path: str) -> dict[str, Any]:
        return self.run_pipeline(pdf_path)
