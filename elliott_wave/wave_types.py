"""
elliott_wave/wave_types.py — Data types for Elliott Wave analysis.

All types are frozen dataclasses for immutability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Literal


class WaveDirection(str, Enum):
    IMPULSE = "impulse"
    CORRECTION = "correction"


class WaveDegree(str, Enum):
    SUPERCYCLE = "supercycle"
    CYCLE = "cycle"
    PRIMARY = "primary"
    INTERMEDIATE = "intermediate"
    MINOR = "minor"
    MINUTE = "minute"


@dataclass(frozen=True)
class WavePoint:
    """Single Elliott wave point (pivot)."""
    index: int              # candle index in df
    price: float
    wave_label: str         # "0", "1", "2", "3", "4", "5", "A", "B", "C"
    timestamp: Optional[object] = None  # pd.Timestamp or datetime


@dataclass(frozen=True)
class WaveSegment:
    """A single wave segment between two pivots."""
    start: WavePoint
    end: WavePoint
    label: str              # "1", "2", "3", "4", "5", "A", "B", "C"
    degree: WaveDegree = WaveDegree.MINOR
    direction: WaveDirection = WaveDirection.IMPULSE

    @property
    def length(self) -> float:
        return abs(self.end.price - self.start.price)

    @property
    def direction_sign(self) -> int:
        """+1 for bullish, -1 for bearish."""
        return 1 if self.end.price > self.start.price else -1


@dataclass(frozen=True)
class WaveCount:
    """One complete Elliott Wave count (primary or alternate)."""
    points: List[WavePoint]
    segments: List[WaveSegment]
    direction: WaveDirection
    degree: WaveDegree
    confidence: float          # [0.0, 1.0]
    is_primary: bool = True    # True = primary count, False = alternative
    label: str = ""            # e.g. "impulse (1-2-3-4-5)" or "zigzag (A-B-C)"

    @property
    def start_price(self) -> float:
        return self.points[0].price if self.points else 0.0

    @property
    def end_price(self) -> float:
        return self.points[-1].price if self.points else 0.0

    @property
    def num_points(self) -> int:
        return len(self.points)

    @property
    def wave_labels(self) -> List[str]:
        return [p.wave_label for p in self.points]

    def get_current_wave(self, current_price: float) -> str:
        """Determine which wave label(s) the current price is between.
        Returns e.g. '3' or 'A-B' (dash-separated for ranges).
        """
        if len(self.points) < 2:
            return ""
        for i in range(len(self.points) - 1):
            p1 = self.points[i]
            p2 = self.points[i + 1]
            lo, hi = min(p1.price, p2.price), max(p1.price, p2.price)
            if lo <= current_price <= hi:
                # Price is in this segment
                if i == 0:
                    return p1.wave_label
                elif i == len(self.points) - 2:
                    return p2.wave_label
                else:
                    return f"{p1.wave_label}-{p2.wave_label}"
        # Price beyond last point — on the last wave
        return self.points[-1].wave_label


@dataclass(frozen=True)
class WaveAnalysis:
    """Complete wave analysis result for one symbol/timeframe."""
    symbol: str
    timeframe: str
    primary: Optional[WaveCount] = None
    alternatives: List[WaveCount] = field(default_factory=list)
    direction: Optional[WaveDirection] = None  # net direction from primary
    confidence: float = 0.0
    conflict: bool = False     # True if primary + alternatives disagree on direction

    def to_dict(self) -> dict:
        """Serializable dict for WebSocket/API."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction.value if self.direction else None,
            "confidence": round(self.confidence, 3),
            "conflict": self.conflict,
            "primary": _count_to_dict(self.primary) if self.primary else None,
            "alternatives": [_count_to_dict(a) for a in self.alternatives],
        }


def _count_to_dict(count: WaveCount) -> dict:
    return {
        "direction": count.direction.value,
        "degree": count.degree.value,
        "confidence": round(count.confidence, 3),
        "is_primary": count.is_primary,
        "label": count.label,
        "points": [
            {"index": p.index, "price": round(p.price, 8), "label": p.wave_label}
            for p in count.points
        ],
        "segments": [
            {
                "label": s.label,
                "start_price": round(s.start.price, 8),
                "end_price": round(s.end.price, 8),
                "direction": s.direction.value,
            }
            for s in count.segments
        ],
    }
