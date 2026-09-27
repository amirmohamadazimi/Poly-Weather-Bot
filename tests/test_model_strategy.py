import pytest

from wxbot.data.polymarket import BookLevel, Bucket
from wxbot.model.base import Calibration
from wxbot.model.normal import NormalMultiModel, bucket_probability
from wxbot.strategy import rules
from wxbot.strategy.sizing import FixedFraction, FractionalKelly

CAL = Calibration(bias_c=0.0, sigma_c=1.5, n=0, source="default")


def test_bucket_ladder_sums_to_one():
    ladder = [Bucket(None, 10, "C")] + [Bucket(x, x, "C") for x in range(11, 26)] + [Bucket(26, None, "C")]
    total = sum(bucket_probability(b, 18.3, 1.7) for b in ladder)
    assert total == pytest.approx(1.0, abs=1e-9)


def test_fahrenheit_two_degree_buckets():
    model = NormalMultiModel(prob_floor=0, prob_ceiling=1)
    vals = {"a": 25.0, "b": 25.0}  # 77 F
    ladder = [Bucket(None, 69, "F")] + [Bucket(x, x + 1, "F") for x in range(70, 86, 2)] + [Bucket(86, None, "F")]
    probs = [model.predict(b, "high", vals, 1, CAL).p_yes for b in ladder]
    assert sum(probs) == pytest.approx(1.0, abs=1e-9)
    assert max(range(len(probs)), key=probs.__getitem__) == ladder.index(Bucket(76, 77, "F"))


def test_bias_correction_and_clamp():
    model = NormalMultiModel(prob_floor=0.01, prob_ceiling=0.99)
    warm_bias = Calibration(bias_c=1.0, sigma_c=1.0, n=50, source="backtest")
    p = model.predict(Bucket(17, 17, "C"), "high", {"a": 18.0}, 1, warm_bias)
    assert p.mu_c == pytest.approx(17.0)
    far = model.predict(Bucket(30, None, "C"), "high", {"a": 18.0}, 1, CAL)
    assert far.p_yes == 0.01  # never 0: the model is never certain


def test_sigma_uses_model_disagreement():
    model = NormalMultiModel()
    p = model.predict(Bucket(18, 18, "C"), "high", {"a": 14.0, "b": 22.0}, 1, CAL)
    assert p.sigma_c == pytest.approx(4.0)


def test_simulate_fill_walks_book_and_caps_share():
    asks = [BookLevel(0.90, 100), BookLevel(0.92, 1000)]
    fill = rules.simulate_fill(asks, budget=50, slippage=0.0, fee_rate=0.0, max_book_share=0.25)
    # first level capped at 25 shares ($22.50), rest at 0.92
    assert fill.levels[0] == (0.9, 25.0)
    assert fill.total == pytest.approx(50.0)
    assert 0.90 < fill.avg_price < 0.92


def test_sizers():
    assert FixedFraction(0.01).stake(1000, 0.9, 0.8) == 10
    assert FractionalKelly(0.25).stake(1000, 0.9, 0.8) == pytest.approx(1000 * 0.5 * 0.25)
    assert FractionalKelly(0.25).stake(1000, 0.7, 0.8) == 0


def _ctx(**kw):
    base = dict(side="NO", model_prob=0.95, market_prob=0.93, entry_price=0.94, liquidity=5000, lead_hours=30,
                n_models=5, forecast_age_min=10, sigma_c=1.7, market_open=True, has_position=False,
                daily_pnl=0, initial_bankroll=1000)
    base.update(kw)
    return rules.Context(**base)


def test_confident_prediction_without_edge_is_not_a_bet(cfg):
    res = rules.evaluate(_ctx(), cfg)
    assert "edge" in rules.failed(res) and "expected_value" in rules.failed(res)
    assert "confidence" not in rules.failed(res)


def test_edge_without_confidence_is_not_a_bet(cfg):
    res = rules.evaluate(_ctx(model_prob=0.6, entry_price=0.4), cfg)
    assert rules.failed(res) == ["confidence"]


def test_all_rules_pass(cfg):
    assert rules.failed(rules.evaluate(_ctx(model_prob=0.97, entry_price=0.88, stake=10), cfg)) == []


@pytest.mark.parametrize("kw,rule", [
    ({"lead_hours": 5}, "time_to_resolution"), ({"liquidity": 10}, "liquidity"),
    ({"n_models": 1}, "data_quality_models"), ({"forecast_age_min": 999}, "data_quality_freshness"),
    ({"sigma_c": 9}, "forecast_uncertainty"), ({"has_position": True}, "no_existing_position"),
    ({"daily_pnl": -80}, "daily_loss_limit"), ({"entry_price": 0.985, "model_prob": 0.99}, "entry_price_range"),
    ({"stake": 0.2}, "position_size"),
])
def test_each_guard(cfg, kw, rule):
    base = dict(model_prob=0.97, entry_price=0.88, stake=10)
    base.update(kw)
    assert rule in rules.failed(rules.evaluate(_ctx(**base), cfg))
