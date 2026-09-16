"""Whole-word matching for BOPA, shared by the analyzers and the client search.

A customer/project term (name or NIF) counts as present in a document only when
it appears as complete word(s): bounded by non-word characters, with a name's
tokens separated by arbitrary whitespace — never as a loose substring. This is
the single rule that keeps BOPA results restricted to genuine mentions of our
own customers: the analyzer never creates a false-positive match (so no alert,
no link), and the per-customer document search never surfaces one either.

The closing **signature block** of a document is excluded from matching. BOPA's
HTML export marks it as ``<p class="signatura">`` — the signer's name and role,
right under the ``<p class="Data">`` place/date line — and a customer named
*only* there is signing the edict as an official (a minister, a comú cònsol, the
president of a court or council), not being mentioned as a party. Left in, one
such customer produced an alert for every edict they signed, which is noise for
the firm. A mention anywhere else (title, body text, tables, annexes that follow
the signature) still matches.

Both callers go through :func:`term_in_text`; :func:`searchable_text` builds the
title+body a document is matched against (signature blocks removed), so the two
stay identical.
"""

import re
from functools import lru_cache

# ``<p class="signatura">…</p>`` as emitted by BOPA's HTML export. Tolerates
# other classes on the same element, single/double/no quotes and any attribute
# order; ``.*?`` stops at the first closing ``</p>`` (signature paragraphs never
# nest other paragraphs).
_SIGNATURE_BLOCK_RE = re.compile(
    r"<p\b[^>]*\bclass\s*=\s*[\"']?[^\"'>]*\bsignatura\b[^>]*>.*?</p\s*>",
    re.IGNORECASE | re.DOTALL,
)


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


def strip_signature_blocks(html_content: str | None) -> str:
    """Remove every ``<p class="signatura">`` block from a document's HTML body.

    Returns ``""`` for a missing body. Each removed block is replaced by a single
    space so the words on either side stay separate tokens.
    """
    if not html_content:
        return ""
    return _SIGNATURE_BLOCK_RE.sub(" ", html_content)


def searchable_text(title: str | None, html_content: str | None) -> str:
    """The title + body a BOPA document is matched against.

    The body's signature blocks are stripped first (see
    :func:`strip_signature_blocks`), so a customer who merely signs the document
    as an official does not match, while a mention anywhere else still does.
    Case is not normalised here: :func:`compile_term` matches with
    ``re.IGNORECASE``, so lowercasing the (potentially large) body as well would
    just be redundant work.
    """
    return f"{title or ''} {strip_signature_blocks(html_content)}"
