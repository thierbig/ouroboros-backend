# tests/test_pricing.py
import pytest
from core.pricing import calculate_cost


class TestPricing:
    def test_anthropic_sonnet(self):
        cost = calculate_cost("anthropic", "claude-sonnet-4-20250514", prompt_tokens=1000, completion_tokens=500)
        assert cost > 0
        assert isinstance(cost, float)

    def test_anthropic_opus(self):
        cost = calculate_cost("anthropic", "claude-opus-4-20250514", prompt_tokens=1000, completion_tokens=500)
        assert cost > 0

    def test_openai_gpt4o(self):
        cost = calculate_cost("openai", "gpt-4o", prompt_tokens=1000, completion_tokens=500)
        assert cost > 0

    def test_unknown_model_returns_zero(self):
        cost = calculate_cost("unknown", "unknown-model", prompt_tokens=1000, completion_tokens=500)
        assert cost == 0.0

    def test_sonnet_cheaper_than_opus(self):
        sonnet = calculate_cost("anthropic", "claude-sonnet-4-20250514", prompt_tokens=1000, completion_tokens=500)
        opus = calculate_cost("anthropic", "claude-opus-4-20250514", prompt_tokens=1000, completion_tokens=500)
        assert sonnet < opus
