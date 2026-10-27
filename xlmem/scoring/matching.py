"""Shared matching foundation for metrics v3 (matching contract MC-1, METRICS_SPEC §3.5).

Pure functions only: normalisation, tokens, language-scoped cue lexicons, targets, whole-token
mentions with longest-match displacement, and mention frames. No metric decisions live here;
those are in xlmem/scoring/support.py and xlmem/scoring/metrics_v3.py.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# Changing anything that affects tokens changes every v3 metric: bump this and the metrics
# version, and regenerate the tier-A spans in data/aliases/*.aliases.v2.yaml.
TOKENIZER_VERSION = "mc1-tok-1"

_NUKTA = "़"
_SENTENCE_BREAK = re.compile(r"[.!?।॥;\n]")

ASSERTED = "ASSERTED"
AFFIRMED = "AFFIRMED"
NEGATED = "NEGATED"
PAST = "PAST"  # provisional frame; resolve_past() turns it into NEGATED or AMBIGUOUS
AMBIGUOUS = "AMBIGUOUS"


def normalize(text: str) -> str:
    """NFC, casefold, `_` -> space, Devanagari nukta folded (फ़ -> फ)."""
    text = unicodedata.normalize("NFC", text).casefold().replace("_", " ")
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(_NUKTA, ""))


def _is_token_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M") or cat == "Nd"


def tokenize(text: str) -> list[str]:
    """Maximal runs of letters, combining marks and digits, after normalize()."""
    tokens: list[str] = []
    current: list[str] = []
    for ch in normalize(text):
        if _is_token_char(ch):
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def split_sentences(text: str) -> list[list[str]]:
    """Tokenized sentences; breaks are . ! ? । ॥ ; and newline."""
    return [toks for part in _SENTENCE_BREAK.split(text) if (toks := tokenize(part))]


def sentence_keys(texts: Iterable[str]) -> set[tuple[str, ...]]:
    """Token tuples of every sentence in the texts (used for 'present in Snapshot A' checks)."""
    return {tuple(s) for t in texts for s in split_sentences(t)}


# --- cue lexicons (METRICS_SPEC §3.5.2) ------------------------------------------------------


@dataclass(frozen=True)
class Lexicon:
    """Cue categories for one language. Pairs are token pairs."""

    neg_before3: frozenset[str] = frozenset()
    neg_after2: frozenset[str] = frozenset()
    neg_pairs_before: frozenset[tuple[str, str]] = frozenset()
    bajay_after2: frozenset[str] = frozenset()
    contrast: frozenset[str] = frozenset()
    affirm_next: frozenset[str] = frozenset()  # "Y instead of X", "Y, not X"
    affirm_pair_after4: frozenset[tuple[str, str]] = frozenset()  # "Y …, न कि X"
    past_before4: frozenset[str] = frozenset()
    past_before3: frozenset[str] = frozenset()
    past_pair_before6: frozenset[tuple[str, str]] = frozenset()
    past_after3: frozenset[str] = frozenset()
    now: frozenset[str] = frozenset()
    ambiguity: frozenset[str] = frozenset()
    user_record: frozenset[str] = frozenset()
    user_answer: frozenset[str] = frozenset()
    pronoun: frozenset[str] = frozenset()

    def merge(self, other: Lexicon) -> Lexicon:
        return Lexicon(
            **{k: getattr(self, k) | getattr(other, k) for k in self.__dataclass_fields__}
        )

    @property
    def negation_tokens(self) -> frozenset[str]:
        return self.neg_before3 | self.neg_after2 | {p[0] for p in self.neg_pairs_before}

    @property
    def cue_tokens(self) -> frozenset[str]:
        """Every token whose unexplained presence makes an uncovered mention AMBIGUOUS."""
        pairs = self.neg_pairs_before | self.affirm_pair_after4 | self.past_pair_before6
        return (
            self.negation_tokens
            | self.bajay_after2
            | self.contrast
            | self.past_before4
            | self.past_before3
            | self.past_after3
            | self.ambiguity
            | {p[0] for p in pairs}  # "used", "instead", "न": not their common partners
            | (self.affirm_next - self.negation_tokens)
        )


def _fs(*items: str) -> frozenset[str]:
    return frozenset(normalize(i) for i in items)


def _pairs(*pairs: tuple[str, str]) -> frozenset[tuple[str, str]]:
    return frozenset((normalize(a), normalize(b)) for a, b in pairs)


LEXICONS: dict[str, Lexicon] = {
    "en": Lexicon(
        neg_before3=_fs("not", "no", "never"),
        neg_pairs_before=_pairs(("instead", "of"), ("rather", "than")),
        contrast=_fs("but"),
        affirm_next=_fs("instead", "not"),
        past_before4=_fs("previously", "earlier", "formerly"),
        past_before3=_fs("was", "were"),
        past_pair_before6=_pairs(("used", "to")),
        now=_fs("now", "currently"),
        ambiguity=_fs("nor", "neither", "however", "although", "though", "longer", "t"),
        user_record=_fs("i", "user"),
        user_answer=_fs("you"),
        pronoun=_fs("he", "she", "they", "him", "her"),
    ),
    "hi": Lexicon(
        neg_after2=_fs("नहीं"),
        neg_before3=_fs("मत"),
        neg_pairs_before=_pairs(("न", "कि")),
        bajay_after2=_fs("बजाय"),
        contrast=_fs("बल्कि"),
        affirm_pair_after4=_pairs(("न", "कि")),
        past_before4=_fs("पहले"),
        past_after3=_fs("था", "थी", "थे"),
        now=_fs("अब", "फ़िलहाल"),
        ambiguity=_fs("लेकिन", "परंतु", "किंतु", "न"),
        user_record=_fs("मैं", "मुझे", "मुझको"),
        user_answer=_fs("आप", "आपको", "तुम", "तुम्हें"),
        pronoun=_fs("वह", "वो", "उसे", "उसको"),
    ),
    # Hinglish (D2: in scope). `the` is deliberately absent: it collides with English.
    "hi-en": Lexicon(
        neg_after2=_fs("nahi", "nahin"),
        neg_pairs_before=_pairs(("na", "ki")),
        contrast=_fs("balki"),
        affirm_pair_after4=_pairs(("na", "ki")),
        past_before4=_fs("pehle"),
        past_after3=_fs("tha", "thi"),
        now=_fs("ab", "abhi"),
        ambiguity=_fs("lekin", "magar"),
        user_record=_fs("main", "mujhe"),
        user_answer=_fs("aap", "aapko", "tum", "tumhe"),
        pronoun=_fs("woh"),
    ),
}


def lexicon_for(context_lang: str) -> Lexicon:
    """English cues are always active; a second lexicon is added for the context language."""
    lex = LEXICONS["en"]
    if context_lang != "en" and context_lang in LEXICONS:
        lex = lex.merge(LEXICONS[context_lang])
    return lex


# --- targets and mentions --------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One matchable token sequence. `owner` is a fact id; `role` is value/updated_value."""

    text: str
    owner: str
    role: str
    tier: str = "canonical"
    tokens: tuple[str, ...] = field(default=())

    def variants(self) -> list[tuple[str, ...]]:
        """The token sequence plus the English ±s variant of its last ASCII token."""
        toks = self.tokens or tuple(tokenize(self.text))
        if not toks:
            return []
        out = [toks]
        last = toks[-1]
        if last.isascii() and last.isalpha():
            if last.endswith("s") and len(last) > 3:
                out.append(toks[:-1] + (last[:-1],))
            elif len(last) > 2:
                out.append(toks[:-1] + (last + "s",))
        return out


def make_target(text: str, owner: str, role: str, tier: str = "canonical") -> Target:
    return Target(text=text, owner=owner, role=role, tier=tier, tokens=tuple(tokenize(text)))


@dataclass(frozen=True)
class Mention:
    """A whole-token occurrence of a target in one sentence, with its frame."""

    target: Target
    sentence: int
    start: int
    end: int
    frame: str
    consumed: tuple[int, ...] = ()


def find_spans(tokens: Sequence[str], seqs: Iterable[tuple[str, ...]]) -> list[tuple[int, int]]:
    """All (start, end) whole-token occurrences of any of the sequences."""
    found: set[tuple[int, int]] = set()
    for seq in seqs:
        n = len(seq)
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i : i + n]) == seq:
                found.add((i, i + n))
    return sorted(found)


def _raw_mentions(
    tokens: Sequence[str], targets: Sequence[Target]
) -> list[tuple[Target, int, int]]:
    """Matches of every target, minus those displaced by a longer match of a different text."""
    raw = [(t, s, e) for t in targets for (s, e) in find_spans(tokens, t.variants())]
    kept = []
    for t, s, e in raw:
        displaced = any(
            s2 <= s and e <= e2 and (e2 - s2) > (e - s) and t2.text != t.text for t2, s2, e2 in raw
        )
        if not displaced:
            kept.append((t, s, e))
    return kept


def _pattern_frame(
    tokens: Sequence[str], start: int, end: int, lex: Lexicon
) -> tuple[str, tuple[int, ...]] | None:
    """The frame given by a supported pattern, with the cue positions it uses; None if none."""
    neg = lex.negation_tokens
    # 1. AFFIRMED (contrast before / NOW near / after-forms), with O5: a NEG cue within the
    #    3 tokens after a contrast- or NOW-affirmed mention cancels the affirmation.
    affirmed: tuple[int, ...] | None = None
    by_contrast_or_now = False
    neg_before3 = any(t in neg for t in tokens[max(0, start - 3) : start])
    for k in range(start - 1, max(-1, start - 3), -1):
        if tokens[k] in neg:
            break
        if tokens[k] in lex.contrast or (tokens[k] in lex.now and not neg_before3):
            affirmed, by_contrast_or_now = (k,), True
            break
    if affirmed is None and end < len(tokens) and tokens[end] in lex.now and not neg_before3:
        affirmed, by_contrast_or_now = (end,), True
    if affirmed is None and end < len(tokens) and tokens[end] in lex.affirm_next:
        affirmed = (end,)
    if affirmed is None:
        for k in range(end, min(end + 4, len(tokens) - 1)):
            pair = (tokens[k], tokens[k + 1])
            if pair in lex.affirm_pair_after4:
                affirmed = (k, k + 1)
                break
            if tokens[k] in neg:
                break
    if affirmed is not None:
        if by_contrast_or_now and any(t in neg for t in tokens[end : end + 3]):
            return AMBIGUOUS, ()  # O5: the statement doesn't establish the current value
        return AFFIRMED, affirmed
    # 2. NEGATED
    for k in range(max(0, start - 3), start):
        if tokens[k] in lex.neg_before3:
            return NEGATED, (k,)
    if start >= 2 and (tokens[start - 2], tokens[start - 1]) in lex.neg_pairs_before:
        return NEGATED, (start - 2, start - 1)
    for k in range(end, min(end + 2, len(tokens))):
        if tokens[k] in lex.neg_after2 or tokens[k] in lex.bajay_after2:
            return NEGATED, (k,)
    # 3. PAST (resolved later in context)
    for k in range(max(0, start - 4), start):
        if tokens[k] in lex.past_before4:
            return PAST, (k,)
    for k in range(max(0, start - 3), start):
        if tokens[k] in lex.past_before3:
            return PAST, (k,)
    for k in range(max(0, start - 6), start - 1):
        if (tokens[k], tokens[k + 1]) in lex.past_pair_before6:
            return PAST, (k, k + 1)
    for k in range(end, min(end + 3, len(tokens))):
        if tokens[k] in lex.past_after3:
            return PAST, (k,)
    return None


def analyze(text: str, targets: Sequence[Target], lex: Lexicon) -> list[Mention]:
    """Mentions of the targets in every sentence of the text, with frames.

    Two passes per sentence: supported patterns first (recording the cue positions they use),
    then AMBIGUOUS for an uncovered mention if any cue token is left unexplained.
    PAST frames are returned as PAST; resolve_past() decides them in context.
    """
    out: list[Mention] = []
    cues = lex.cue_tokens
    for s_idx, tokens in enumerate(split_sentences(text)):
        raw = _raw_mentions(tokens, targets)
        framed: list[tuple[Target, int, int, str | None, tuple[int, ...]]] = []
        consumed: set[int] = set()
        for t, s, e in raw:
            pf = _pattern_frame(tokens, s, e, lex)
            if pf is None:
                framed.append((t, s, e, None, ()))
            else:
                framed.append((t, s, e, pf[0], pf[1]))
                consumed.update(pf[1])
        for t, s, e, frame, used in framed:
            if frame is None:
                unexplained = any(tok in cues and i not in consumed for i, tok in enumerate(tokens))
                frame = AMBIGUOUS if unexplained else ASSERTED
            out.append(Mention(t, s_idx, s, e, frame, used))
    return out


def has_now_cue(text: str, lex: Lexicon) -> bool:
    return any(tok in lex.now for s in split_sentences(text) for tok in s)


def resolve_past(mentions: Sequence[Mention], text: str, lex: Lexicon) -> list[Mention]:
    """PAST -> NEGATED if the text has a NOW cue or asserts another value of the same fact,
    otherwise AMBIGUOUS (METRICS_SPEC §3.5.3, O4). Other frames are unchanged."""
    now = has_now_cue(text, lex)
    out = []
    for m in mentions:
        if m.frame == PAST:
            other = any(
                o.target.owner == m.target.owner
                and o.target.role != m.target.role
                and o.frame in (ASSERTED, AFFIRMED)
                for o in mentions
            )
            m = Mention(
                m.target, m.sentence, m.start, m.end, NEGATED if now or other else AMBIGUOUS
            )
        out.append(m)
    return out
