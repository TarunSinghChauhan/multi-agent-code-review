"""Split source code into pieces that fit an LLM prompt.

The review agents used to send only the first 3000 characters of the submitted
code, so anything after that was silently never reviewed even though the API
accepts up to MAX_CODE_CHARS (6000 by default). These helpers let the agents
review every accepted character, a bounded number of calls at a time.
"""

DEFAULT_CHUNK_CHARS = 3000
DEFAULT_MAX_CHUNKS = 4


def split_for_llm(
    code: str,
    limit: int = DEFAULT_CHUNK_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[tuple[int, str]]:
    """Return up to max_chunks pieces of code as (lines_before, text) pairs.

    Pieces break on line boundaries so no statement is cut in half. A single line
    longer than limit is cut by characters. lines_before is the number of lines that
    come before the piece in the original code; add it to a line number reported
    for the piece to get the line number in the whole file. Text beyond max_chunks
    pieces is dropped, which bounds the cost of one review.
    """
    if limit < 1 or max_chunks < 1:
        raise ValueError("limit and max_chunks must be at least 1")
    if len(code) <= limit:
        return [(0, code)]

    chunks: list[tuple[int, str]] = []
    current: list[str] = []
    current_len = 0
    current_start = 0  # lines before the piece being built
    line_index = 0

    def flush() -> None:
        nonlocal current, current_len, current_start
        if current:
            chunks.append((current_start, "".join(current)))
        current, current_len = [], 0
        current_start = line_index

    for line in code.splitlines(keepends=True):
        if len(line) > limit:
            flush()
            current_start = line_index
            for i in range(0, len(line), limit):
                chunks.append((line_index, line[i : i + limit]))
            line_index += 1
            current_start = line_index
        else:
            if current_len + len(line) > limit:
                flush()
            current.append(line)
            current_len += len(line)
            line_index += 1
        if len(chunks) >= max_chunks:
            return chunks[:max_chunks]
    flush()
    return chunks[:max_chunks]


def shift_line(line_number, offset: int):
    """Move a line number reported for a piece to its place in the whole file.

    Anything that is not a real integer (None, a string, a bool) is returned as is.
    """
    if isinstance(line_number, int) and not isinstance(line_number, bool):
        return line_number + offset
    return line_number
