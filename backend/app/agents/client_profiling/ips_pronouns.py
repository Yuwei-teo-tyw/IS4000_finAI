"""IS-91: deterministic pronoun pass over AI-written IPS text.

Within one list of statements the first keeps "The client ..."; each following one uses she/he/they instead of
repeating it. The pronoun comes only from the client's recorded gender (Client.gender) - never guessed from a name;
no recorded gender -> they/their with plural verb agreement. Sentences that would read badly are left unchanged.
Evidence quotes are never passed through here."""
import re
from typing import Optional

_SETS = {"female": ("She", "Her", "her", "her"), "male": ("He", "His", "his", "him"),
         "neutral": ("They", "Their", "their", "them")}
_F, _M = {"f", "female", "woman", "ms", "mrs", "miss", "madam", "she"}, {"m", "male", "man", "mr", "sir", "he"}
_ADV = {"also", "still", "always", "never", "only", "really", "mainly", "currently", "generally", "typically", "now", "often", "usually"}
_IRREG = {"is": "are", "has": "have", "does": "do", "was": "were"}
_LEAD = re.compile(r"^The client(?:'s|’s)?(?=\s|$)")


def pronoun_kind(gender: Optional[str]) -> str:
    g = (gender or "").strip().lower().rstrip(".")
    return "female" if g in _F else "male" if g in _M else "neutral"


def _plural(v: str) -> str:
    low = v.lower()
    if low in _IRREG:
        return _IRREG[low]
    if low.endswith("ies") and len(low) > 4:
        return v[:-3] + "y"
    if low.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return v[:-2]
    if low.endswith("s") and not low.endswith(("ss", "us")):
        return v[:-1]
    return v  # will / would / can / must ... are invariant


def pronounize(text: str, kind: str) -> str:
    """Pronoun form of a statement that starts with 'The client ...'; unchanged if it cannot be done safely."""
    subj, poss, poss_l, obj = _SETS[kind]
    m = _LEAD.match(text or "")
    if not m:
        return text
    rest = text[m.end():]
    if m.group(0).lower().endswith("s") and m.group(0) != "The client":  # possessive: "The client's capital ..."
        head, tail = poss, rest
    else:
        words = rest.split()
        i = 0
        while i < len(words) and words[i].lower() in _ADV:
            i += 1
        if i >= len(words) or not re.match(r"^[A-Za-z]+$", words[i]):
            return text
        if kind == "neutral":
            v = words[i]
            if v.lower() in {"not", "and", "or", "to", "of", "in"} or not (v.lower() in _IRREG or v.lower().endswith("s") or v.lower() in
                                                                           {"will", "would", "can", "could", "should", "must", "may", "might", "cannot"}):
                return text  # past tense / unknown verb form: keep "The client" rather than risk bad grammar
            words[i] = _plural(v)
        head, tail = subj, " " + " ".join(words)
        # a pronoun is only safe if the sentence has no other "the client" left that now reads oddly: keep as is
    out = head + tail
    return re.sub(r"\bthe client(?:'s|’s)", poss_l, out)  # remaining possessives: "the client's capital" -> "her capital"


_THEY = re.compile(r"\b(They|they|Their|their|Theirs|theirs|Them|them|Themselves|themselves)\b(\s+[A-Za-z]+)?")
_IRREG_SG = {"are": "is", "have": "has", "do": "does", "were": "was"}


def _singular(v: str) -> str:
    low = v.lower()
    if low in _IRREG_SG:
        return _IRREG_SG[low]
    if low in {"will", "would", "can", "could", "should", "must", "may", "might", "cannot", "not", "and", "or", "also", "still", "always",
               "never", "only", "really", "mainly", "currently", "generally", "typically", "now", "often", "usually", "need", "needs"}:
        return v if low != "need" else "needs"
    if low.endswith(("s", "ed")) or not low.isalpha():
        return v
    if low.endswith(("ch", "sh", "x", "z", "o")):
        return v + "es"
    if low.endswith("y") and low[-2:-1] not in "aeiou":
        return v[:-1] + "ies"
    return v + "s"


def unify_pronouns(text: str, gender: Optional[str]) -> str:
    """Known gender: any they/their/them in the text becomes she/her or he/his/him, so one client never mixes pronouns."""
    kind = pronoun_kind(gender)
    if kind == "neutral" or not text:
        return text
    subj, poss, poss_l, obj = _SETS[kind]

    def sub(m: re.Match) -> str:
        w, nxt = m.group(1), m.group(2) or ""
        low = w.lower()
        if low == "they":
            new, nxt = subj if w[0].isupper() else subj.lower(), (" " + _singular(nxt.strip())) if nxt else ""
        elif low in ("their", "theirs"):
            new = poss if w[0].isupper() else poss_l
        elif low == "them":
            new = obj.capitalize() if w[0].isupper() else obj
        else:
            new = "Herself" if kind == "female" else "Himself"
            new = new if w[0].isupper() else new.lower()
        return new + nxt
    return _THEY.sub(sub, text)


def apply_pronouns(texts: list[str], gender: Optional[str]) -> list[str]:
    """First statement keeps 'The client' (at most once); every later one is pronoun-ised (same length/order as input).
    With a known gender every they/their/them is also unified to that gender."""
    kind = pronoun_kind(gender)
    out = [t if i == 0 else pronounize(t, kind) for i, t in enumerate(texts)]
    return [unify_pronouns(t, gender) for t in out]


def _key(t: str) -> tuple[set, set]:
    low = re.sub(r"(?<=\d),(?=\d)", "", t.lower())
    low = re.sub(r"(\d)\s?(million|mn|mm)\b", r"\1m", low)
    low = re.sub(r"(\d)\s?-?\s?(years?|yrs?)\b", r"\1y", low)
    low = re.sub(r"(\d)\s+(?=[a-z%])", r"\1", low)
    nums = set(re.findall(r"\d+(?:\.\d+)?[a-z%]*", low))
    from .ips_generate import _words  # lazy: avoid import cycle
    return nums, _words(t)


def is_near_duplicate(a: str, b: str) -> bool:
    na, wa = _key(a)
    nb, wb = _key(b)
    if na != nb:
        return False
    if a.strip().lower() == b.strip().lower():
        return True
    if not na or not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def drop_duplicates(texts: list[str]) -> list[str]:
    out: list[str] = []
    for t in texts:
        if not any(is_near_duplicate(t, o) for o in out):
            out.append(t)
    return out
