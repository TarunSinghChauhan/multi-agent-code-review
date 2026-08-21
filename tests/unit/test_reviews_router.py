import math
from types import SimpleNamespace

from src.api.routers.reviews import clean_nans, serialize_result


def test_clean_nans_replaces_nan():
    assert clean_nans(float("nan")) == 0.0


def test_clean_nans_leaves_normal_values():
    assert clean_nans({"cost": 0.05}) == {"cost": 0.05}


def make_pydantic_like(**kwargs):
    """Mimic a Pydantic model with model_dump(), without needing the real class."""
    obj = SimpleNamespace(**kwargs)
    obj.model_dump = lambda: kwargs
    return obj


def test_serialize_result_converts_pydantic_issues():
    issue = make_pydantic_like(issue_type="eval_usage", severity="high")
    final_state = {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "issues": [issue],
        "fix_proposals": [],
        "severity_counts": {"high": 1},
        "total_cost_usd": 0.05,
        "review_summary": "summary text",
    }
    result = serialize_result(final_state)
    assert result["total_issues"] == 1
    assert result["issues"][0]["issue_type"] == "eval_usage"


def test_serialize_result_accepts_plain_dict_issues():
    final_state = {
        "job_id": "job_2",
        "filename": "app.py",
        "language": "python",
        "issues": [{"issue_type": "bare_except", "severity": "medium"}],
        "fix_proposals": [],
        "severity_counts": {},
        "total_cost_usd": 0.0,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert result["total_issues"] == 1
    assert result["issues"][0]["issue_type"] == "bare_except"


def test_serialize_result_rounds_cost():
    final_state = {
        "job_id": "job_3",
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [],
        "severity_counts": {},
        "total_cost_usd": 0.123456789,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert result["total_cost_usd"] == 0.123457


def test_serialize_result_handles_missing_optional_fields():
    final_state = {"job_id": "job_4"}
    result = serialize_result(final_state)
    assert result["total_issues"] == 0
    assert result["severity_counts"] == {}
    assert result["total_cost_usd"] == 0.0


def test_serialize_result_converts_fix_proposals():
    proposal = make_pydantic_like(issue_title="Fix eval", explanation="use literal_eval")
    final_state = {
        "job_id": "job_5",
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [proposal],
        "severity_counts": {},
        "total_cost_usd": 0.0,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert len(result["fix_proposals"]) == 1
    assert result["fix_proposals"][0]["issue_title"] == "Fix eval"
