import pytest

from src.agents.chunking import split_for_llm, shift_line


def numbered(n, width=9):
    """n lines, each exactly width + 1 characters including the newline."""
    return "".join(f"{i:0{width}d}\n" for i in range(n))


def test_short_code_is_one_piece_with_no_offset():
    assert split_for_llm("x = 1\n") == [(0, "x = 1\n")]


def test_code_exactly_at_the_limit_is_not_split():
    code = "a" * 3000
    assert split_for_llm(code) == [(0, code)]


def test_long_code_is_split_on_line_boundaries_without_losing_text():
    code = numbered(500)  # 5000 characters
    pieces = split_for_llm(code, limit=3000)
    assert len(pieces) == 2
    assert all(len(text) <= 3000 for _, text in pieces)
    assert all(text.endswith("\n") for _, text in pieces)
    assert "".join(text for _, text in pieces) == code


def test_offsets_count_the_lines_before_each_piece():
    code = numbered(500)
    pieces = split_for_llm(code, limit=3000)
    lines = code.splitlines()
    for offset, text in pieces:
        # the first line of every piece is where the offset says it is
        assert lines[offset] == text.splitlines()[0]


def test_a_single_overlong_line_is_cut_by_characters():
    code = "a" * 7000 + "\nshort\n"
    pieces = split_for_llm(code, limit=3000, max_chunks=10)
    assert [len(t) for _, t in pieces] == [3000, 3000, 1001, 6]
    assert [o for o, _ in pieces] == [0, 0, 0, 1]  # "short" is the second line
    assert "".join(t for _, t in pieces) == code


def test_the_number_of_pieces_is_capped():
    code = numbered(2000)  # 20000 characters
    pieces = split_for_llm(code, limit=3000, max_chunks=3)
    assert len(pieces) == 3
    assert sum(len(t) for _, t in pieces) < len(code)  # the rest is deliberately dropped


def test_empty_code_still_gives_one_piece():
    assert split_for_llm("") == [(0, "")]


@pytest.mark.parametrize("limit,max_chunks", [(0, 1), (-5, 1), (10, 0)])
def test_invalid_limits_are_rejected(limit, max_chunks):
    with pytest.raises(ValueError):
        split_for_llm("x", limit=limit, max_chunks=max_chunks)


def test_shift_line_adds_the_offset_to_real_integers_only():
    assert shift_line(5, 100) == 105
    assert shift_line(None, 100) is None
    assert shift_line("7", 100) == "7"
    assert shift_line(True, 100) is True
