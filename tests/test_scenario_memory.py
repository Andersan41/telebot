import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.scenario_memory import ScenarioMemory, ScenarioStats


class TestScenarioStats:
    def test_winrate(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        stats.total_wins = 60
        stats.total_losses = 40
        assert stats.winrate == 0.6

    def test_winrate_zero_when_no_data(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        assert stats.winrate == 0.0

    def test_closed_count(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        stats.total_wins = 5
        stats.total_losses = 3
        stats.total_breakeven = 2
        assert stats.closed_count == 10

    def test_expectancy(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        stats.total_wins = 60
        stats.total_losses = 40
        stats.avg_rr = 2.0
        # E = 0.6 * 2.0 - 0.4 * 1.0 = 1.2 - 0.4 = 0.8
        assert stats.expectancy == pytest.approx(0.8, abs=0.01)

    def test_is_reliable(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        stats.total_wins = 20
        stats.total_losses = 5
        # 25 < 30 → not reliable
        assert not stats.is_reliable

        stats.total_losses = 15
        # 35 >= 30 → reliable
        assert stats.is_reliable

    def test_sample_label(self):
        stats = ScenarioStats(scenario_name="test", symbol="BTC/USDT")
        stats.total_wins = 5
        assert stats.sample_label == "insufficient"

        stats.total_losses = 10
        assert stats.sample_label == "limited"

        stats.total_losses = 50
        assert stats.sample_label == "moderate"

        stats.total_losses = 100
        assert stats.sample_label == "sufficient"


class TestScenarioMemory:
    def setup_method(self):
        self.memory = ScenarioMemory()

    def test_record_win(self):
        self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.5)
        stats = self.memory.get_stats("BTC/USDT", "Sweep+BOS+OB")
        assert stats is not None
        assert stats.total_wins == 1
        assert stats.winrate == 1.0

    def test_record_loss(self):
        self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "loss", rr=-1.0)
        stats = self.memory.get_stats("BTC/USDT", "Sweep+BOS+OB")
        assert stats.total_losses == 1
        assert stats.winrate == 0.0

    def test_multiple_outcomes(self):
        for _ in range(60):
            self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.0)
        for _ in range(40):
            self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "loss", rr=-1.0)

        stats = self.memory.get_stats("BTC/USDT", "Sweep+BOS+OB")
        assert stats.winrate == pytest.approx(0.6, abs=0.01)
        assert stats.closed_count == 100
        assert stats.is_reliable

    def test_record_observation(self):
        self.memory.record_observation("BTC/USDT", "CHoCH+OB")
        stats = self.memory.get_stats("BTC/USDT", "CHoCH+OB")
        assert stats.total_seen == 1
        assert stats.total_activated == 0

    def test_get_symbol_stats(self):
        self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.0)
        self.memory.record_outcome("BTC/USDT", "CHoCH+OB", "loss", rr=-1.0)
        self.memory.record_outcome("ETH/USDT", "Sweep+BOS+OB", "win", rr=1.5)

        btc_stats = self.memory.get_symbol_stats("BTC/USDT")
        assert len(btc_stats) == 2

    def test_get_reliable_scenarios(self):
        # Not reliable
        self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.0)
        assert len(self.memory.get_reliable_scenarios("BTC/USDT")) == 0

        # Make it reliable
        for _ in range(30):
            self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.0)
        assert len(self.memory.get_reliable_scenarios("BTC/USDT")) == 1

    def test_get_best_scenarios(self):
        for _ in range(30):
            self.memory.record_outcome("BTC/USDT", "Sweep+BOS+OB", "win", rr=2.0)
        for _ in range(30):
            self.memory.record_outcome("BTC/USDT", "CHoCH+OB", "win", rr=1.0)

        best = self.memory.get_best_scenarios("BTC/USDT", min_trades=30)
        assert len(best) == 2
        # Sweep+BOS+OB has higher avg_rr
        assert best[0].scenario_name == "Sweep+BOS+OB"
