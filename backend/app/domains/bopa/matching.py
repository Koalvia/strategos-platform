"""Whole-word matching for BOPA, shared by the analyzers and the client search.

A customer/project term (name or NIF) counts as present in a document only when
it appears as complete word(s): bounded by non-word characters, with a name's
tokens separated by arbitrary whitespace — never as a loose substring. This is
the single rule that keeps BOPA results restricted to genuine mentions of our
own customers: the analyzer never creates a false-positive match (so no alert,
no link), and the per-customer document search never surfaces one either.

Both callers go through :func:`term_in_text`; :func:`searchable_text` builds the
lowercased title+body a document is matched against, so the two stay identical.
"""

import re
from functools import lru_cache


@lru_cache(maxsize=4096)
def compile_term(term: str) -> re.Pattern[str] | None:
    """Compile a case-insensitive, whole-token pattern for ``term``.

    The term must occur as complete word(s): its tokens (split on whitespace) are
    escaped and rejoined with ``\\s+`` so multi-word names still match across
    newlines/extra spaces, and the whole thing is bounded by ``(?<!\\w)`` /
    ``(?!\\w)`` so it never matches inside a larger word. Returns ``None`` for a
    blank term. Cached so each distinct term compiles once per process.
    """
    tokens = term.split()
    if not tokens:
        return None
    body = r"\s+".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


def term_in_text(term: str | None, text: str) -> bool:
    """Whether ``term`` occurs as whole word(s) in ``text`` (see :func:`compile_term`)."""
    if not term or not term.strip():
        return False
    pattern = compile_term(term.strip())
    return pattern is not None and pattern.search(text) is not None


def searchable_text(title: str | None, html_content: str | None) -> str:
    """The lowercased title + body a BOPA document is matched against."""
    return f"{title or ''} {html_content or ''}".lower()
