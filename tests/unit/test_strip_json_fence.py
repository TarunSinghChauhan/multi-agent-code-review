from src.agents.security import strip_json_fence


def test_strips_json_labeled_fence():
    raw = '```json\n[{"key": "value"}]\n```'
    assert strip_json_fence(raw) == '[{"key": "value"}]'


def test_strips_plain_fence():
    raw = '```\n[{"key": "value"}]\n```'
    assert strip_json_fence(raw) == '[{"key": "value"}]'


def test_returns_unchanged_when_no_fence():
    raw = '[{"key": "value"}]'
    assert strip_json_fence(raw) == raw


def test_prefers_json_labeled_fence_check_first():
    raw = '```json\n{"a": 1}\n```'
    result = strip_json_fence(raw)
    assert result == '{"a": 1}'


def test_handles_empty_string():
    assert strip_json_fence("") == ""
