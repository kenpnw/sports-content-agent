"""Content strategy module for platform-specific social post planning."""

import json
import sys
from typing import Any

from openai import OpenAI

from config import DEEPSEEK_API_KEY
from config import BASE_URL
from config import CHAT_MODEL
from config import MAX_TOKENS


ANGLE_TYPES = {
    "controversial_take",
    "tactical_breakdown",
    "player_spotlight",
    "underdog_story",
    "stat_anomaly",
}
CONTENT_TYPES = {"player_card", "tactical_diagram", "stat_infographic", "quote_card"}
BADGE_TYPES = {"爆", "稳", "强"}


class StrategyEngine:
    """Builds structured content strategies for Hupu, Weibo, and Xiaohongshu."""

    def __init__(self) -> None:
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY is missing. Set it in your .env file.")
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)
        self.platform_rules: dict[str, dict[str, str]] = {
            "hupu": {"tone": "数据驱动、理性辩论", "format": "标题+9图+长文", "style": "硬核球迷"},
            "weibo": {"tone": "热点话题、简洁有力", "format": "话题标签+轮播图+短文", "style": "大众传播"},
            "xiaohongshu": {"tone": "教学向、易懂", "format": "竖版图+emoji+话题", "style": "科普友好"},
        }

    def _extract_text(self, response: Any) -> str:
        """Extracts text content from OpenAI API response."""
        return response.choices[0].message.content.strip()

    def identify_viral_angles(self, report: dict[str, Any]) -> list[dict[str, str]]:
        system_prompt = (
            "你是中国篮球社媒内容策略专家。基于输入的球探报告数据，识别3到5个适合中文平台传播的爆款角度。"
            "必须仅返回JSON数组，每个元素字段为："
            "angle_type, hook, target_platform, reasoning。"
            "angle_type只能是：controversial_take, tactical_breakdown, player_spotlight, "
            "underdog_story, stat_anomaly。"
            "target_platform只能是：hupu, weibo, xiaohongshu。"
            "所有文案使用简体中文。"
        )
        try:
            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(report, ensure_ascii=False)},
                ],
            )
            raw_text = self._extract_text(response)
        except Exception as exc:
            raise RuntimeError(f"Failed to identify viral angles: {exc}") from exc

        # 清理 markdown 代码块
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []

        sanitized: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            angle_type = str(item.get("angle_type", "")).strip()
            target_platform = str(item.get("target_platform", "")).strip().lower()
            if angle_type not in ANGLE_TYPES:
                continue
            if target_platform not in self.platform_rules:
                continue
            sanitized.append(
                {
                    "angle_type": angle_type,
                    "hook": str(item.get("hook", "")).strip(),
                    "target_platform": target_platform,
                    "reasoning": str(item.get("reasoning", "")).strip(),
                }
            )
        return sanitized

    def generate_platform_content(
        self, report: dict[str, Any], angle: dict[str, str], platform: str
    ) -> dict[str, Any]:
        platform_key = platform.lower()
        if platform_key not in self.platform_rules:
            raise ValueError(f"Unsupported platform: {platform}")
        rules = self.platform_rules[platform_key]
        system_prompt = (
            "你是中文体育社媒资深编辑。请仅使用简体中文生成内容，并仅返回JSON对象。"
            f"平台：{platform_key}；语气：{rules['tone']}；形式：{rules['format']}；风格：{rules['style']}。"
            "输出字段：title, caption, hashtags, content_type, visual_suggestions, badge_suggestion。"
            "content_type只能是：player_card, tactical_diagram, stat_infographic, quote_card。"
            "badge_suggestion只能是：爆, 稳, 强。"
            "hashtags必须是字符串数组，visual_suggestions必须是字符串数组。"
        )
        payload = {"report": report, "angle": angle, "platform": platform_key, "rules": rules}
        try:
            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            raw_text = self._extract_text(response)
        except Exception as exc:
            raise RuntimeError(f"Failed to generate platform content for {platform_key}: {exc}") from exc

        default_item: dict[str, Any] = {
            "title": "",
            "caption": "",
            "hashtags": [],
            "content_type": "stat_infographic",
            "visual_suggestions": [],
            "badge_suggestion": "稳",
        }
        # 清理 markdown 代码块
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return []
            return default_item

        content_type = str(data.get("content_type", "stat_infographic")).strip()
        badge = str(data.get("badge_suggestion", "稳")).strip()
        hashtags = data.get("hashtags", [])
        visual_suggestions = data.get("visual_suggestions", [])
        if not isinstance(hashtags, list):
            hashtags = []
        if not isinstance(visual_suggestions, list):
            visual_suggestions = []

        normalized: dict[str, Any] = {
            "title": str(data.get("title", "")).strip(),
            "caption": str(data.get("caption", "")).strip(),
            "hashtags": [str(tag).strip() for tag in hashtags if str(tag).strip()],
            "content_type": content_type if content_type in CONTENT_TYPES else "stat_infographic",
            "visual_suggestions": [str(item).strip() for item in visual_suggestions if str(item).strip()],
            "badge_suggestion": badge if badge in BADGE_TYPES else "稳",
        }
        return normalized

    def generate_full_strategy(self, report: dict[str, Any]) -> dict[str, Any]:
        angles = self.identify_viral_angles(report)
        platform_content: dict[str, list[dict[str, Any]]] = {
            "hupu": [],
            "weibo": [],
            "xiaohongshu": [],
        }
        for angle in angles:
            platform = angle.get("target_platform", "")
            try:
                content_item = self.generate_platform_content(report, angle, platform)
                content_item["angle_type"] = angle.get("angle_type", "")
                content_item["hook"] = angle.get("hook", "")
                content_item["reasoning"] = angle.get("reasoning", "")
                platform_content[platform].append(content_item)
            except Exception as e:
                print(f"⚠️ 生成内容失败 ({platform}): {e}")
                continue
        return {"angles": angles, "platform_content": platform_content}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python content_agent/strategy_engine.py <report_json_path>")
    report_json_path = sys.argv[1]
    with open(report_json_path, "r", encoding="utf-8") as input_file:
        report_data = json.load(input_file)
    engine = StrategyEngine()
    strategy = engine.generate_full_strategy(report_data)
    print(json.dumps(strategy, ensure_ascii=False, indent=2))
