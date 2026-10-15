from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ModeDecision:
    mode: str
    available: bool
    selected_key: Optional[str] = None
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    preset: Dict[str, Any] = field(default_factory=dict)
