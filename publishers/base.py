from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass, field


@dataclass
class PublishPlan:
    platform: str
    mode: str
    status: str
    title: str
    notes: list[str] = field(default_factory=list)
    payload_path: str = ""
    preview_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
