from __future__ import annotations

import os
from pathlib import Path

from publishers.base import PublishPlan
from storage.file_store import ensure_dir, write_json, write_text


def prepare_douyin_publish(root: Path, package: dict, assets: dict) -> dict:
    publish_root = ensure_dir(root / "publish")
    payload = {
        "platform": "douyin",
        "mode": "credential_gated",
        "title": package["title"],
        "caption": package["caption"],
        "hashtags": package.get("hashtags", []),
        "cover_text": package.get("cover_text", ""),
        "assets": assets,
        "script": package.get("short_video_script", []),
    }
    payload_path = publish_root / "publish_payload.json"
    notes_path = publish_root / "publish_notes.md"
    write_json(payload_path, payload)

    has_token = bool(os.getenv("DOUYIN_ACCESS_TOKEN"))
    has_client_key = bool(os.getenv("DOUYIN_CLIENT_KEY"))
    has_media = bool(assets.get("douyin_poster"))

    if has_token and has_client_key and has_media:
        status = "api_credentials_detected"
        notes = [
            "Douyin credentials are present.",
            "This project prepares the payload and assets for the official Douyin publish flow.",
            "A live publish request still needs endpoint-specific request wiring after app approval.",
        ]
    else:
        status = "needs_credentials"
        notes = [
            "Douyin official publish flow requires approved open platform credentials and user authorization.",
            "This project prepares the payload, poster asset, and script so the account operator can publish quickly.",
        ]

    write_text(
        notes_path,
        "\n".join(
            [
                "# Douyin Publish Notes",
                "",
                f"Status: {status}",
                "",
                "Required for live direct posting:",
                "- DOUYIN_CLIENT_KEY",
                "- DOUYIN_ACCESS_TOKEN",
                "- approved content publish permission",
                "",
                "Current workflow already prepares:",
                "- caption",
                "- hashtags",
                "- cover text",
                "- script",
                "- poster asset",
            ]
        ),
    )

    plan = PublishPlan(
        platform="douyin",
        mode="credential_gated",
        status=status,
        title=package["title"],
        notes=notes,
        payload_path=str(payload_path),
        preview_path=str(notes_path),
    )
    return plan.to_dict()
