"""Both LLM agents must review the whole accepted input, not just its first 3000 characters."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.security import security_agent, calculate_llm_cost
from src.agents.static_analysis import static_analysis_agent

TAIL_MARKER = "TAIL_MARKER_ONLY_IN_THE_LAST_LINE"


def big_code():
    # ~5000 characters of harmless code; the marker sits well past character 3000.
    body = "".join(f"value_{i:04d} = {i}\n" for i in range(240))
    return body + f"# {TAIL_MARKER}\n"


def make_state(code):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "code": code,
        "total_cost_usd": 0.0,
    }


def reply(content, prompt_tokens=100, completion_tokens=50):
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content))]
    r.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return r


def finding(line):
    return json.dumps([{
        "issue_type": "x", "severity": "low", "line_number": line,
        "title": "t", "description": "d", "suggestion": "s",
    }])


def prompts_of(client):
    return [c.kwargs["messages"][1]["content"] for c in client.chat.completions.create.call_args_list]


CASES = [
    ("src.agents.security._get_client", security_agent),
    ("src.agents.static_analysis._get_client", static_analysis_agent),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_code_past_3000_characters_reaches_the_model(target, agent):
    assert len(big_code()) > 3000
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("[]"))
    with patch(target, return_value=client):
        await agent(make_state(big_code()))
    assert any(TAIL_MARKER in p for p in prompts_of(client))


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_small_input_still_costs_one_call(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("[]"))
    with patch(target, return_value=client):
        await agent(make_state("x = 1\n"))
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_line_numbers_are_relative_to_the_whole_file(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[reply(finding(2)), reply(finding(2))])
    code = big_code()
    with patch(target, return_value=client):
        result = await agent(make_state(code))
    lines = sorted(i.line_number for i in result["issues"] if i.issue_type == "x")
    assert lines[0] == 2
    assert lines[1] > 100  # the second piece starts far into the file
    # and that line really is the second line of the second piece
    second_prompt = prompts_of(client)[1]
    assert code.splitlines()[lines[1] - 1] == second_prompt.split("```")[1].splitlines()[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_cost_is_summed_over_every_call(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("[]", 1000, 500))
    with patch(target, return_value=client):
        result = await agent(make_state(big_code()))
    calls = client.chat.completions.create.await_count
    assert calls >= 2
    assert result["total_cost_usd"] == pytest.approx(calculate_llm_cost(1000, 500) * calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_one_failing_piece_keeps_the_findings_of_the_others(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[RuntimeError("api down"), reply(finding(3))])
    with patch(target, return_value=client):
        result = await agent(make_state(big_code()))
    found = [i for i in result["issues"] if i.issue_type == "x"]
    assert len(found) == 1
    assert result["total_cost_usd"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_a_piece_with_unparseable_json_is_skipped_not_fatal(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[reply("not json"), reply(finding(1))])
    with patch(target, return_value=client):
        result = await agent(make_state(big_code()))
    assert len([i for i in result["issues"] if i.issue_type == "x"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_the_number_of_model_calls_is_bounded(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("[]"))
    with patch(target, return_value=client):
        await agent(make_state("x = 1\n" * 100_000))
    assert client.chat.completions.create.await_count <= 4
