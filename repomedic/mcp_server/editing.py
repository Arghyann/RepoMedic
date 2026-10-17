"""Search/replace editing that tolerates the indentation slips small models make."""
import difflib


class EditError(ValueError):
    pass


def _reindent(block: list[str], delta: str, remove: int) -> list[str]:
    out = []
    for line in block:
        if not line.strip():
            out.append(line)
            continue
        stripped = line[remove:] if line[:remove].strip() == "" else line.lstrip()
        out.append(delta + stripped)
    return out


def apply_search_replace(text: str, search: str, replace: str) -> str:
    """Replace exactly one occurrence of `search`. Falls back to whitespace-insensitive line matching."""
    if not search.strip():
        raise EditError("`search` must contain the exact existing code to replace.")
    count = text.count(search)
    if count == 1:
        return text.replace(search, replace, 1)
    if count > 1:
        raise EditError(f"`search` matches {count} places; include more surrounding lines so it is unique.")

    lines = text.splitlines(keepends=True)
    want = [ln.strip() for ln in search.strip("\n").splitlines()]
    while want and not want[-1]:
        want.pop()
    hits = []
    for i in range(len(lines) - len(want) + 1):
        if all(lines[i + j].strip() == want[j] for j in range(len(want))):
            hits.append(i)
    if len(hits) != 1:
        if not hits:
            raise EditError("`search` text was not found in the file. Copy it exactly from read_file (without line numbers).")
        raise EditError(f"`search` matches {len(hits)} places; include more surrounding lines so it is unique.")

    start = hits[0]
    file_indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    search_first = next(ln for ln in search.strip("\n").splitlines() if ln.strip())
    search_indent = len(search_first) - len(search_first.lstrip())
    repl_lines = replace.strip("\n").splitlines()
    repl_lines = _reindent(repl_lines, file_indent, search_indent) if repl_lines else []
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    new_block = [ln + newline for ln in repl_lines]
    return "".join(lines[:start] + new_block + lines[start + len(want):])


def unified_diff(before: str, after: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))
