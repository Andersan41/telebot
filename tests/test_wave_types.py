"""Tests for elliott_wave/wave_types.py — data types."""
import pytest
from elliott_wave.wave_types import (
    WavePoint, WaveSegment, WaveCount, WaveAnalysis,
    WaveDirection, WaveDegree,
)


class TestWavePoint:
    def test_creation(self):
        wp = WavePoint(index=10, price=100.0, wave_label="1")
        assert wp.index == 10
        assert wp.price == 100.0
        assert wp.wave_label == "1"

    def test_frozen(self):
        wp = WavePoint(index=0, price=50.0, wave_label="A")
        with pytest.raises(AttributeError):
            wp.price = 60.0


class TestWaveSegment:
    def test_creation(self):
        start = WavePoint(index=0, price=100.0, wave_label="0")
        end = WavePoint(index=10, price=110.0, wave_label="1")
        seg = WaveSegment(start=start, end=end, label="1")
        assert seg.length == 10.0
        assert seg.direction_sign == 1

    def test_bearish_direction(self):
        start = WavePoint(index=0, price=110.0, wave_label="2")
        end = WavePoint(index=10, price=100.0, wave_label="3")
        seg = WaveSegment(start=start, end=end, label="3")
        assert seg.direction_sign == -1
        assert seg.length == 10.0


class TestWaveCount:
    def test_impulse_count(self):
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="1"),
            WavePoint(index=20, price=105.0, wave_label="2"),
            WavePoint(index=30, price=125.0, wave_label="3"),
            WavePoint(index=40, price=120.0, wave_label="4"),
            WavePoint(index=50, price=135.0, wave_label="5"),
        ]
        segments = [
            WaveSegment(start=points[i], end=points[i+1], label=str(i+1))
            for i in range(5)
        ]
        count = WaveCount(
            points=points,
            segments=segments,
            direction=WaveDirection.IMPULSE,
            degree=WaveDegree.MINOR,
            confidence=0.75,
            label="impulse (1-2-3-4-5)",
        )
        assert count.start_price == 100.0
        assert count.end_price == 135.0
        assert count.num_points == 6
        assert count.wave_labels == ["0", "1", "2", "3", "4", "5"]

    def test_frozen(self):
        count = WaveCount(
            points=[], segments=[],
            direction=WaveDirection.IMPULSE,
            degree=WaveDegree.MINOR,
            confidence=0.5,
        )
        with pytest.raises(AttributeError):
            count.confidence = 0.9


class TestWaveAnalysis:
    def test_to_dict_empty(self):
        analysis = WaveAnalysis(symbol="BTC/USDT", timeframe="1h")
        d = analysis.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert d["direction"] is None
        assert d["primary"] is None
        assert d["alternatives"] == []
        assert d["conflict"] is False

    def test_to_dict_with_primary(self):
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="1"),
        ]
        segments = [
            WaveSegment(start=points[0], end=points[1], label="1"),
        ]
        primary = WaveCount(
            points=points,
            segments=segments,
            direction=WaveDirection.IMPULSE,
            degree=WaveDegree.MINOR,
            confidence=0.6,
            label="impulse",
        )
        analysis = WaveAnalysis(
            symbol="ETH/USDT",
            timeframe="4h",
            primary=primary,
            direction=WaveDirection.IMPULSE,
            confidence=0.6,
        )
        d = analysis.to_dict()
        assert d["symbol"] == "ETH/USDT"
        assert d["direction"] == "impulse"
        assert d["primary"]["confidence"] == 0.6
        assert len(d["primary"]["points"]) == 2
        assert d["primary"]["points"][0]["label"] == "0"
