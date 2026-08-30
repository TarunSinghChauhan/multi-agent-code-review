from src.agents.security import calculate_llm_cost


def test_known_token_counts():
    cost = calculate_llm_cost(prompt_tokens=1000, completion_tokens=500)
    expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
    assert cost == expected


def test_zero_tokens_is_zero_cost():
    assert calculate_llm_cost(0, 0) == 0.0


def test_only_prompt_tokens():
    cost = calculate_llm_cost(prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == 0.15


def test_only_completion_tokens():
    cost = calculate_llm_cost(prompt_tokens=0, completion_tokens=1_000_000)
    assert cost == 0.60


def test_completion_tokens_cost_more_than_prompt_tokens():
    prompt_only = calculate_llm_cost(1000, 0)
    completion_only = calculate_llm_cost(0, 1000)
    assert completion_only > prompt_only
