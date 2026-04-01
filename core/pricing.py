"""LLM API cost calculation based on provider pricing."""

PRICING = {
    "anthropic": {
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.0},
    },
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    },
}


def calculate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate the cost of an LLM API call based on token usage.

    Prices are per 1 million tokens. Returns 0.0 for unknown provider/model
    combinations. Supports fuzzy model matching by prefix.
    """
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model)

    if not model_pricing:
        for model_name, pricing in provider_pricing.items():
            if model.startswith(model_name.rsplit("-", 1)[0]):
                model_pricing = pricing
                break

    if not model_pricing:
        return 0.0

    input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]
    return round(input_cost + output_cost, 6)
