from __future__ import annotations

from pathlib import Path

from publishers.base import PublishPlan
from storage.file_store import ensure_dir, write_json, write_text


def prepare_hupu_publish(root: Path, package: dict) -> dict:
    publish_root = ensure_dir(root / "publish")
    payload = {
        "platform": "hupu",
        "mode": "manual_review",
        "title": package["title"],
        "article": package["article_markdown"],
        "tags": package.get("tags", []),
        "next_action": "Copy the title and article body into Hupu manually. Review tone before posting.",
    }
    payload_path = publish_root / "publish_payload.json"
    notes_path = publish_root / "publish_notes.md"
    write_json(payload_path, payload)
    write_text(
        notes_path,
        "\n".join(
            [
                "# Hupu Publish Notes",
                "",
                "1. Review title and article body.",
                "2. Confirm tone matches current Hupu discussion style.",
                "3. Paste content into Hupu post editor manually.",
                "4. Add any topical tags that make sense before posting.",
            ]
        ),
    )
    plan = PublishPlan(
        platform="hupu",
        mode="manual_review",
        status="ready_for_manual_post",
        title=package["title"],
        notes=[
            "No verified public official Hupu posting API is configured in this project.",
            "The workflow prepares a polished publish payload and review checklist.",
        ],
        payload_path=str(payload_path),
        preview_path=str(notes_path),
    )
    return plan.to_dict()
