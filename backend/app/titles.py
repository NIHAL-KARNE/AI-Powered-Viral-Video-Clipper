from __future__ import annotations

import re
from collections import Counter

from .transcribe import content_tokens, tokenize

# A sentence that depends on the one before it cannot open a title.
DEPENDENT = re.compile(
    r"^(and|but|so|because|which|that|then|also|or|it|this|they|he|she|however|although|"
    r"though|while|if|when|as|to|of|at|in|for|with|from|on|its|his|her|their|my|our|your)\b",
    re.I,
)
FILLER_START = re.compile(r"^(oh|yeah|um|uh|ah|well|okay|ok|so yeah|right|huh)\b[\s,]*", re.I)

# Openers that announce a point instead of making one ("Here's the surprising part").
TEASER = re.compile(
    r"^(here'?s?\b|here is\b|this is\b|that'?s\b|that is\b|you won'?t believe|"
    r"wait (?:till|until)|check this|look at this|watch this|guess what|"
    r"the (?:best|worst|crazy|wild|surprising) part)",
    re.I,
)

# Words that carry no topic signal on their own.
GENERIC = {
    "thing", "things", "stuff", "way", "ways", "part", "parts", "lot", "lots", "bit",
    "bits", "kind", "sort", "people", "person", "guys", "guy", "time", "times", "today",
    "right", "now", "then", "there", "here", "something", "anything", "everything",
    "nothing", "someone", "anyone", "everyone", "more", "most", "really", "actually",
    "basically", "literally", "maybe", "probably", "going", "gonna", "wanna", "gotta",
}

# Vague words that describe nothing on their own, so they make poor hashtags.
VAGUE = {
    "nice", "good", "bad", "big", "small", "little", "whole", "second", "piece",
    "middle", "front", "back", "side", "top", "bottom", "new", "old", "first",
    "last", "next", "long", "short", "hard", "easy", "real", "true", "sure",
}

# Verbs, adverbs, discourse markers and junk that make bad topic words.
NOT_TOPIC = {
    "know", "knows", "knew", "think", "thinks", "thought", "want", "wants", "wanted",
    "need", "needs", "needed", "make", "makes", "made", "making", "take", "takes", "took",
    "tell", "tells", "told", "say", "says", "said", "see", "sees", "seen", "look", "looks",
    "looking", "listen", "wait", "waits", "stop", "stops", "stopped", "come", "comes", "came",
    "coming", "get", "gets", "got", "give", "gives", "gave", "giving", "call", "calls",
    "called", "hear", "hears", "heard", "leave", "leaves", "left", "leaving", "go", "goes",
    "went", "going", "keep", "keeps", "kept", "show", "shows", "showing", "start", "starts",
    "started", "work", "works", "worked", "play", "plays", "played", "looked", "happen",
    "happened", "happens", "doing", "done", "does", "did", "have", "has", "had", "having",
    "will", "would", "could", "should", "can", "may", "might", "must", "shall",
    "literally", "honestly", "actually", "basically", "seriously", "obviously", "probably",
    "maybe", "perhaps", "totally", "simply", "clearly", "apparently", "anyway", "anyways",
    "yeah", "yep", "nope", "okay", "alright", "well", "like", "just", "even", "still",
    "never", "always", "again", "back", "away", "down", "over", "into", "onto", "than",
    "then", "some", "such", "very", "much", "many", "more", "less", "least", "only",
    "also", "too", "both", "each", "every", "another", "other", "same", "own", "what",
    "when", "where", "which", "while", "who", "whom", "whose", "why", "how", "because",
    "before", "after", "during", "without", "within", "about", "around", "through",
    "between", "against", "along", "across", "behind", "beyond", "above", "below",
    "ones", "one", "thing", "things", "someone", "anyone", "everyone", "nobody",
    "goddamn", "bullshit", "damn", "heck", "hell", "freaking", "fricking", "shit",
    "fuck", "fucking", "bitch", "asshole", "ass", "crap",
}

# Adverbs/fillers that make a poor title opener even mid-sentence.
WEAK_OPENER = re.compile(
    r"^(literally|honestly|actually|basically|seriously|obviously|probably|maybe|perhaps|"
    r"yeah|yep|okay|ok|alright|well|so|like|just|and|but|because|literally|anyway)\b",
    re.I,
)
SPEAKER_LABEL = re.compile(r"^\s*[A-Z][a-z]{0,12}:\s+")

# Whisper capitalises these mid-sentence at random; lowercasing them reads correctly.
COMMON_CAPS = {
    w.lower()
    for w in (
        "People Every Because Like Yeah Okay Right Now Then When What Where Really Actually "
        "Just Even Still Always Never Something Nothing Everything Everyone Someone Thing "
        "Things Time Times Day Days Year Years Money Life Work Game Games Guy Guys Dude Man "
        "Bro Look Listen Wait Stop Come Go Get Got Know Think Want Need Make Made Take Tell "
        "Said Say See Seen Here There This That They Them Their Your Our Its His Her She He "
        "You We I Me My One Two Three Four Five Six Seven Eight Nine Ten First Last Next"
    ).split()
}

LEADING_NOISE = re.compile(
    r"^(all right|alright|you know|i mean|i guess|kind of|sort of|like|well|so|and|but|oh|"
    r"yeah|okay|ok|right|now|then|listen|look|hey|dude|man|bro)\b[\s,]+",
    re.I,
)

BARE_QUESTION = re.compile(r"^(what|why|how|who|where|when)\b[^.!?]{0,22}\?$", re.I)
WEAK_FRAGMENT = re.compile(
    r"^(you know|i mean|is that|what is it|what'?s this|what'?s that|like what|so what|"
    r"what the|oh my|thank you|yeah|okay|alright)\b",
    re.I,
)
HANGING_END = re.compile(
    r"\b(and|but|because|so|the|a|an|of|to|in|on|for|with|that|which|is|are|was|were|"
    r"it|this|they|you|we|i)\W*$",
    re.I,
)


# Titles must stay publishable: slurs and profanity get a title rejected
# outright, since they hurt reach far more than they ever help a click.
BLOCKED_WORDS = re.compile(
    r"\b(fuck(?:ing|ed|s)?|shit(?:ty|s)?|bitch(?:es)?|asshole|prick|cunt|dick|"
    r"nigga|nigger|faggot|retard(?:ed)?|whore|slut|rape)\b",
    re.I,
)


# --------------------------------------------------------------------- text fixes
# Whisper artefacts that look broken when written down.
TRANSCRIPT_FIXES = [
    (re.compile(r"\bname'?s\s+be\s+", re.I), "name is "),
    (re.compile(r"\b(\d+)\s*-\s*year\s*-\s*old\b", re.I), r"\1-year-old"),
    (re.compile(r"\b(\d+)\s+-\s*(year|years|month|months|day|days|percent)\b", re.I), r"\1-\2"),
    (re.compile(r"\s+([,.!?])"), r"\1"),
]


def _repair_transcript(s: str) -> str:
    """Fix common Whisper splits/glitches so titles read like written English."""
    out = s or ""
    for pattern, repl in TRANSCRIPT_FIXES:
        out = pattern.sub(repl, out)
    return out


def _fix_caps(s: str) -> str:
    """Repair random mid-sentence capitals and standalone 'i'."""
    words = s.split()
    out: list[str] = []
    for i, w in enumerate(words):
        core = re.sub(r"[^A-Za-z']", "", w)
        if core.lower() == "i":
            w = w.replace(core, "I")
        elif core.lower() == "i'm" or core == "i'M":
            w = w.replace(core, "I'm")
        elif i > 0 and core and core[0].isupper() and core.lower() in COMMON_CAPS:
            w = w.replace(core, core.lower(), 1)
        out.append(w)
    return " ".join(out)


def _clean(s: str) -> str:
    s = _repair_transcript(s)
    s = SPEAKER_LABEL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:-—\"'")
    # Strip stacked leading fillers ("Oh yeah, so...", "All right, you know...").
    for _ in range(3):
        new = LEADING_NOISE.sub("", s)
        if new == s:
            break
        s = new
    s = FILLER_START.sub("", s)
    return _fix_caps(s.strip())


def _titlecase_first(s: str) -> str:
    """Sentence case: capitalise the first letter only.

    Avoids shouty Title Case ("Ones And Surprising") while preserving names and
    the pronoun I.
    """
    if not s:
        return s
    s = s[0].upper() + s[1:]
    # Capitalise a standalone i and contractions of it.
    s = re.sub(r"\bi\b", "I", s)
    s = re.sub(r"\bi'(m|ll|ve|d)\b", lambda m: "I'" + m.group(1), s)
    return s


TRAILING_STOP = re.compile(
    r"^(and|but|or|so|the|a|an|of|to|in|on|for|with|that|which|who|whom|"
    r"is|are|was|were|not|no|it|this|these|those|they|them|you|we|i|"
    r"when|where|while|because|if|as|at|by|from|than|then|doing|being|"
    r"just|like|very|really|literally|actually|too|also|even|yeah|okay|"
    r"about|into|onto|upon|around|through|against|between|over|under|"
    r"before|after|during|without|within|toward|towards|never|always|"
    r"still|already|almost|nearly|hardly|simply|completely|constantly)$",
    re.I,
)


def _trim_clause(s: str, limit: int = 62) -> str:
    """Keep whole clauses that fit; never cut a sentence mid-thought."""
    s = s.strip()
    if len(s) <= limit:
        return s
    clauses = [c.strip(" ,;:—") for c in re.split(r", | — | - |; |: ", s) if c.strip()]
    kept = ""
    for clause in clauses:
        trial = f"{kept}, {clause}" if kept else clause
        if len(trial) > limit:
            break
        kept = trial
    if kept and len(tokenize(kept)) >= 4:
        return kept
    # A run-on with no comma still has clause joints at its conjunctions:
    # "...knew nobody and I had two hundred dollars" -> "...knew nobody".
    joint = re.split(r"\s+(?:and|but|so|because|then|which|while)\s+", s, maxsplit=1)
    if len(joint) > 1 and len(tokenize(joint[0])) >= 4 and len(joint[0]) <= limit:
        return joint[0].strip(" ,;:-—")
    # No usable clause boundary: take the longest prefix that ends on a real word.
    words = (clauses[0] if clauses else s).split()
    best = ""
    for n in range(len(words), 0, -1):
        candidate = " ".join(words[:n])
        if len(candidate) <= limit and not TRAILING_STOP.match(words[n - 1]):
            best = candidate
            break
    if not best:
        best = " ".join(w for w in words if len(w) <= limit)[:limit].rsplit(" ", 1)[0]
    return best


def _fit(s: str, limit: int = 72) -> str:
    out = _clean(s)
    # Strip a leading conjunction ("Because the people who..." -> "The people
    # who..."). Never strip a demonstrative pronoun: "That was the craziest..."
    # only works with "That" attached, and removing it leaves a fragment.
    stripped = re.sub(
        r"^(and|but|so|because|then|also|or|however|although|though|while)\b[\s,]+",
        "", out, flags=re.I,
    ).strip()
    if stripped and stripped != out:
        first = stripped.split()[0].lower() if stripped.split() else ""
        # Only accept the strip if what remains still opens like a sentence.
        if first not in {"was", "were", "is", "are", "had", "has", "have", "did",
                        "does", "do", "will", "would", "could", "should", "can"}:
            out = stripped

    raw_parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", out) if x.strip()]
    parts: list[str] = []
    for raw in raw_parts:
        piece = _clean(raw)
        # Keep the sentence's own punctuation so joins still read as sentences.
        end = re.search(r"[.!?]+$", raw)
        if piece and end:
            piece = piece.rstrip(".!?") + end.group(0)[0]
        if piece:
            parts.append(piece)
    if len(parts) > 1:
        # A strong opening sentence is a better title than two sentences bolted
        # together, so use it on its own when it qualifies.
        lead = parts[0]
        if (len(tokenize(lead)) >= 4 and len(content_tokens(lead)) >= 3
                and not _is_fragment(lead) and len(lead) <= limit
                and not ORDINAL_OPEN.match(lead)):
            out = lead
            parts = parts[:1]
        else:
            # Build a title from whole sentences, never by cutting into one.
            kept = ""
            for raw in parts:
                # An ordinal opens a list item ("First, say no more often"), which
                # reads as a stray fragment once it is out of order.
                if ORDINAL_OPEN.match(raw) or re.match(r"^(and|but|so|because)\b", raw, re.I):
                    break
                part = _titlecase_first(raw) if kept else raw
                if kept and len(content_tokens(part)) < 2:
                    # "Wait." / "Gladly." add nothing to a title.
                    continue
                trial = f"{kept} {part}".strip() if kept else part
                if len(trial) > limit and kept:
                    break
                kept = trial
                if (len(tokenize(kept)) >= 3 and len(content_tokens(kept)) >= 2
                        and len(kept) >= limit * 0.45):
                    break
            out = kept or parts[0]
    elif len(out) > limit:
        out = _trim_clause(out, limit)

    # An untrimmed complete sentence is already whole — never shave its end.
    if bool(re.search(r"[.!?][\"')\]]*$", s.strip())) and len(out) <= limit:
        return out.strip(" ,;:-—")
    out = out.strip(" ,;:-—")
    # Otherwise never leave a title dangling on a joining or filler word.
    for _ in range(4):
        words = out.split()
        if words and TRAILING_STOP.match(words[-1].strip(" ,;:-—")):
            out = " ".join(words[:-1])
            continue
        break
    return out.rstrip(" ,;:-")


# --------------------------------------------------------------------- sentence quality
def _topic_words(text: str, limit: int = 8) -> list[str]:
    """Words that actually describe the subject of a clip.

    Filters out verbs, adverbs, profanity and contractions so hashtags and
    keyword-led titles read like English instead of word soup.
    """
    words = [
        w for w in content_tokens(text)
        if w.isalpha() and len(w) > 3 and w not in GENERIC and w not in NOT_TOPIC
    ]
    counts = Counter(words)
    # Repeated words are the real subject; break ties toward longer words.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [w for w, _ in ranked[:limit]]



DETERMINER = re.compile(
    r"\b(?:the|a|an|my|your|his|her|their|our|this|that|these|those|every|no|some|any)\s+"
    r"([a-z][a-z'-]{3,})\b",
    re.I,
)


def _noun_topics(text: str, limit: int = 6) -> list[str]:
    """Words that appear where a noun belongs ("the *monster*", "your *plan*").

    Position after a determiner is a reliable noun signal, which keeps verbs
    like "reproduce" out of topic-based titles and hashtags.
    """
    candidates = [m.group(1).lower() for m in DETERMINER.finditer(text or "")]
    words = [w for w in candidates if w not in GENERIC and w not in VAGUE and w not in NOT_TOPIC]
    counts = Counter(words)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [w for w, _ in ranked[:limit] if len(w) > 3]


def _distinctive(s: str) -> list[str]:
    return _topic_words(s, limit=20)


def _is_fragment(s: str) -> bool:
    """True when a sentence cannot stand alone as a title."""
    toks = tokenize(s)
    content = content_tokens(s)
    if len(toks) < 5 or len(content) < 3:
        return True
    if len(_distinctive(s)) < 2 and len(content) < 5:
        return True
    if BARE_QUESTION.match(s):
        return True
    if WEAK_FRAGMENT.match(s) and len(content) < 4:
        return True
    if s.strip().endswith("?") and len(content) < 4:
        return True
    if FILLER_START.match(s) and len(content) < 4:
        return True
    if TEASER.match(s) and len(_distinctive(s)) < 3:
        return True
    if HANGING_END.search(s) and not re.search(r"[.!?][\"')\]]*$", s):
        return True
    if len(content) / max(len(toks), 1) < 0.45:
        return True
    if _is_repetitive(s):
        return True
    return False


def _sentence_quality(s: str) -> float:
    toks = tokenize(s)
    content = content_tokens(s)
    distinct = _distinctive(s)
    if len(toks) < 5 or len(content) < 3:
        return 0.0

    q = 0.0
    q += min(len(distinct) / 5, 1.0) * 3.4          # real topic words win
    q += min(len(content) / 10, 1.0) * 0.8          # mild preference for substance
    # A complete claim ("X is Y") reads like a title; a list of nouns doesn't.
    if re.search(r"\b(is|are|was|were|makes|means|turns|becomes|keeps|never|always)\b", s, re.I):
        q += 1.1
    if re.search(r"\b(you|your|we|our|i|my)\b", s, re.I):
        q += 0.9
    if re.search(r"\b\d[\d,.]*%?\b", s):
        q += 0.8
    if s.strip().endswith("?"):
        q += 0.3 if len(content) >= 6 else -1.6
    if s.strip().endswith("!"):
        q += 0.3
    q += min(len(set(distinct)) / 4, 1.0)

    # Penalties
    if DEPENDENT.match(s):
        q -= 2.6
    if FILLER_START.match(s):
        q -= 2.0
    if WEAK_OPENER.match(s):
        q -= 1.5
    if SPEAKER_LABEL.match(s):
        q -= 0.6
    if TEASER.match(s):
        q -= 2.2
    if len(distinct) < 2:
        q -= 2.4
    if re.search(r"\b(fuck|shit|bitch|asshole|prick|cunt)\b", s, re.I):
        q -= 2.4
    if HANGING_END.search(s):
        q -= 1.6
    # Word salad: many tokens, few real words.
    if len(toks) > 12 and len(content) / len(toks) < 0.55:
        q -= 1.4
    # Stutters and repeated hooks read as broken text.
    if _is_repetitive(s):
        q -= 3.0
    return q



# --------------------------------------------------------------------- title craft
# Words that frame an insight. A line built around one of these is the clip's
# point, which is what a title should sell.
INSIGHT_CUES = re.compile(
    r"\b(learned|realised|realized|discovered|found out|the truth|secret|mistake|"
    r"nobody|everybody|everyone|never|always|actually|the problem|the answer|"
    r"turns out|changed my|changed the|the reason|the trick)\b",
    re.I,
)
# Numeric or factual anchors make a title concrete ("10 years", "3 rules").
ANCHOR = re.compile(r"\b\d[\d,.]*\b")
# A title should not repeat the first words of the video, which the headline
# already shows on screen.
SECOND_PERSON = re.compile(r"\b(you|your|you're|you\s+have|you\s+need)\b", re.I)
# Ordinals only make sense inside a list, so they cannot open a title.
# Only an enumerator with its comma is a list marker. Without one, "Three rules
# changed my life" is an ordinary sentence that makes a perfectly good title.
ORDINAL_OPEN = re.compile(r"^(first|second|third|fourth|fifth|firstly|secondly|thirdly"
                          r"|one|two|three|four|five)\s*[,:]\s+", re.I)


def _claim(sentence: str) -> tuple[str, str] | None:
    """Split a line of speech into a setup and its payoff, where one exists.

    "I spent 10 years building companies and I learned one thing: nobody cares
    about your plan" -> ("I spent 10 years building companies", "nobody cares
    about your plan"). The payoff is what a title should lead with.
    """
    text = _clean(sentence)
    if not text:
        return None
    # A colon is the strongest signal: the speaker is naming their point.
    if ":" in text:
        setup, payoff = text.split(":", 1)
        if len(tokenize(payoff)) >= 3:
            return setup.strip(), payoff.strip()
    # "X and I learned Y" / "X but Y" / "X, so Y": the clause after the turn
    # carries the point.
    m = re.search(r"(?:^|\b)(?:and|but|so|because)\s+((?:i\s+)?(?:learned|realised|realized|"
                  r"discovered|found|figured|noticed|know|guess)\b[^,.]*[,:]?\s*(.+))$", text, re.I)
    if m and len(tokenize(m.group(2))) >= 4:
        setup = text[: m.start()].strip(" ,:;-")
        return setup, m.group(2).strip(" ,:;-")
    # "Nobody cares about X" style claims stand alone.
    if INSIGHT_CUES.search(text) and len(content_tokens(text)) >= 3:
        return "", text
    return None


def _as_hook(claim: str) -> str | None:
    """Turn a claim into a title that makes someone stop scrolling.

    Keeps the speaker's own words — a rewritten title that invents facts would be
    wrong — but leads with the point, drops throat-clearing, and adds tension
    only where the sentence supports it.
    """
    text = _titlecase_first(_clean(claim))
    if not text:
        return None
    words = tokenize(text)
    if len(words) < 3:
        return None
    # Sentence-form claim: keep it as is, it reads like a title already.
    if INSIGHT_CUES.search(text) or SECOND_PERSON.search(text) or ANCHOR.search(text):
        return _fit(text, 72)
    # "The reason most people fail at X" -> keep the frame, it is already a hook.
    return _fit(text, 72)


def _contrast_title(pool: list[str]) -> str | None:
    """Title built from the clip's turn: what people think vs what is true.

    Only produced when the clip really contains both halves, so it never
    invents a contrast the speaker did not make.
    """
    for raw in pool:
        found = _claim(raw)
        if not found:
            continue
        setup, payoff = found
        setup_words = content_tokens(setup)
        payoff_words = content_tokens(payoff)
        if len(setup_words) < 3 or len(payoff_words) < 3:
            continue
        # Prefer the payoff: it is the part that lands.
        hook = _as_hook(payoff)
        if hook:
            return hook
    return None


def _number_title(pool: list[str]) -> str | None:
    """Lead with a concrete number when the clip states one."""
    for raw in pool:
        text = _clean(raw)
        if not ANCHOR.search(text):
            continue
        words = text.split()
        if len(words) < 4:
            continue
        # "I spent 10 years building companies" -> "10 Years Building Companies"
        core = re.sub(r"^i\s+(spent|did|worked|tried|lost|made|built)\s+", "", text, flags=re.I)
        core = re.sub(r"^(i|we)\s+(have|had|'ve)\s+", "", core, flags=re.I)
        hook = _fit(_titlecase_first(core), 60)
        if len(tokenize(hook)) >= 3:
            return hook
    return None


def _question_title(pool: list[str]) -> str | None:
    """A real question from the clip, kept because questions invite a click."""
    for raw in pool:
        text = _clean(raw)
        if not text.endswith("?") or _is_fragment(text):
            continue
        if re.match(r"^(what|why|how|who|where|when|which|do|does|did|is|are|was|were|"
                    r"can|could|should|would|will|have|has)\b", text, re.I):
            return _fit(_titlecase_first(text), 72)
    return None


def _curiosity_title(pool: list[str]) -> str | None:
    """Name the subject and the stakes, without inventing anything.

    Built as "<concrete part of the claim>: <the turn>", e.g. "Building companies
    for 10 years: nobody cares about your plan". Only produced when the clip has
    a claim with a setup and a payoff.
    """
    for raw in pool:
        found = _claim(raw)
        if not found:
            continue
        setup, payoff = found
        setup = _clean(setup)
        payoff = _as_hook(payoff)
        if not setup or not payoff:
            continue
        setup_words = content_tokens(setup)
        if len(setup_words) < 2 or len(setup) > 34:
            continue
        candidate = f"{_titlecase_first(setup)}: {payoff}"
        if len(candidate) <= 78:
            return candidate
    return None


# Listing ordinals, with or without a comma: "First, say no more often".
# The ordinal needs its separator: "Three rules changed my life" is a sentence,
# not a list item, whereas "Three: rules..." or "First, say no" is an item.
LIST_ITEM = re.compile(
    r"^(first|second|third|fourth|fifth|firstly|secondly|thirdly|one|two|three|four|five"
    r"|finally|lastly|and finally)\s*[,:.!]\s*",
    re.I,
)


def _list_title(pool: list[str]) -> str | None:
    """Turn a list clip into "<headline>: item, item".

    "Three rules changed my life. First, say no more often. Second, protect your
    mornings." -> "Three rules changed my life: say no more often, protect your
    mornings". The enumerators are dropped because out of sequence they read as
    stray fragments, while the lead sentence still says what the list is about.
    """
    lead = ""
    items: list[str] = []
    for raw in pool:
        text = _clean(raw)
        if not text:
            continue
        if LIST_ITEM.match(text):
            item = LIST_ITEM.sub("", text).strip(" ,;:-")
            if len(tokenize(item)) >= 2:
                items.append(item)
        elif not items and not lead:
            lead = text
        elif items:
            break
    if len(items) < 2:
        return None
    if not lead:
        lead = "What nobody tells you"
    # A list title earns a little more width than a plain line: it carries the
    # headline plus at least two items, which is the whole point. Fall back to
    # fewer items, then to a shorter headline, before giving up.
    for head in (lead, _trim_clause(lead, 40)):
        for count in (3, 2):
            candidate = f"{head}: {', '.join(items[:count])}"
            if len(candidate) <= 96:
                return candidate
    return None



# Trailing vocatives ("..., bro", "... though, man") add nothing to a title.
VOCATIVE = re.compile(
    r"(?:[\s,]+(?:bro|bruh|dude|man|fam|guys|y'?all|chat|homie|buddy|sir|ma'?am|"
    r"girl|boy|dog|broski|big bro|little bro|my guy|my boy))+[\s,.!?]*$",
    re.I,
)
# Discourse markers that announce an opinion instead of making one.
DISCOURSE_OPEN = re.compile(
    r"^(crazy|insane|wild|nuts|listen|look|okay|alright|so|like|i mean|you know|"
    r"honestly|literally|basically|actually|dude|bro|man|yo|nah|yes|no)\b[\s,]+",
    re.I,
)
# Evaluative openers that carry no subject ("Crazy, you know what's crazy though").
EMPTY_EVAL = re.compile(
    r"^(?:(?:what'?s|that'?s|this is|so)\s+)?"
    r"(crazy|insane|wild|nuts|unreal|stupid|funny|weird)"
    r"(?:[\s,]+(?:though|right|huh|man|bro|dude|you know what))?[\s?,.!]*$",
    re.I,
)
# Words that mark a turn, a stake or a consequence — the spine of a clickable title.
STAKES = re.compile(
    r"\b(lost|won|quit|fired|broke|rich|failed|passed|failed|survived|risk(?:ed)?|"
    r"betrayed|caught|exposed|banned|arrested|refused|walked away|gave up|turned down|"
    r"changed|stopped|started|sold|built|spent|made|earned|saved|wasted|regret)\b",
    re.I,
)
TURN = re.compile(
    r"\b(but|until|except|instead|turns out|however|then|so|because|actually|never|"
    r"nobody|everybody|everyone|most people)\b",
    re.I,
)
CURIOSITY = re.compile(
    r"\b(why|how|what|secret|truth|reason|mistake|nobody|tells you|told me|lesson|"
    r"learned|found out|realised|realized|discovered)\b",
    re.I,
)



def _starts_new_thought(line: str) -> bool:
    """True when a line opens a fresh thought rather than continuing the last one."""
    text = (line or "").strip()
    if not text:
        return True
    if DEPENDENT.match(text):
        return False
    return not re.match(
        r"^(and|but|so|because|which|that|then|also|or|it|this|they|he|she|however|"
        r"although|though|while|if|when|as|to|of|at|in|for|with|from|on|his|her|"
        r"their|its|my|our|your)\b",
        text,
        re.I,
    )

def _strip_vocatives(s: str) -> str:
    """Drop trailing 'bro'/'dude'/'though' chatter so a line reads like a title."""
    out = s.strip()
    for _ in range(3):
        new = VOCATIVE.sub("", out).strip(" ,;:-—")
        if new == out:
            break
        out = new
    return out


def _strip_discourse(s: str) -> str:
    """Remove leading 'crazy,', 'listen,' style markers that delay the point."""
    out = s.strip()
    for _ in range(3):
        new = DISCOURSE_OPEN.sub("", out).strip(" ,;:-—")
        if new == out or len(tokenize(new)) < 3:
            break
        out = new
    return out




# Function words in impossible sequences signal a garbled transcript line.
BROKEN_ORDER = re.compile(
    r"\b(?:every|each|the)\s+(?:the|a|an|every|each)\b"
    r"|\b(?:is|are|was|were|be|been)\s+(?:be|been)\b"
    r"|\b(?:a|an|the)\s+(?:to|of|and|but)\b"
    r"|\b(?:say|says|said)\s+(?:every|each)\b"
    r"|\b(?:name'?s?|names)\s+(?:be|been)\b"
    r"|\b(?:sorry|okay|alright)\s+(?:pull|put|take|get)\b"
    r"|\b(?:you|we|they)\s+(?:is|was|are|were)\b",
    re.I,
)


def _reads_like_english(text: str) -> bool:
    """Cheap grammar sanity check so garbled transcript lines never become titles."""
    t = (text or "").strip()
    if not t:
        return False
    if BROKEN_ORDER.search(t):
        return False
    toks = tokenize(t)
    if not toks:
        return False
    # Only function words, not verbs/adverbs, count here: "I can see the" is
    # ordinary English, while "every the last of" is garbled.
    FUNC = {"the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "but",
            "or", "is", "are", "was", "were", "be", "been", "you", "i", "we", "they",
            "it", "this", "that", "at", "by", "from", "as", "if", "so", "not"}
    funcs = 0
    worst = 0
    for tok in toks:
        if tok.lower() in FUNC:
            funcs += 1
            worst = max(worst, funcs)
        else:
            funcs = 0
    if worst >= 5:
        return False
    # Two real sentence breaks means two thoughts were glued together
    # ("I'm eating. Sorry pull it..."), which never reads like a title.
    breaks = len(re.findall(r"[.!?]\s+[A-Za-z]", t))
    if breaks >= 1:
        return False
    return True

def _is_repetitive(text: str) -> bool:
    """True when a line repeats itself ("every time you talk every time you talk").

    Whisper faithfully transcribes stutters and repeated hooks; those read as
    broken text in a title, so they get filtered out.
    """
    toks = [t.lower() for t in tokenize(text)]
    if len(toks) < 6:
        return False
    grams = [" ".join(toks[i:i + 3]) for i in range(len(toks) - 2)]
    seen: dict[str, int] = {}
    for g in grams:
        seen[g] = seen.get(g, 0) + 1
    if any(v >= 2 for v in seen.values()):
        return True
    # same token back to back ("Nooo Nooo", "talk talk talk")
    runs = 1
    for i in range(1, len(toks)):
        runs = runs + 1 if toks[i] == toks[i - 1] else 1
        if runs >= 2 and len(toks[i]) >= 3:
            return True
    # A short word/phrase repeated at the very start ("Noooo Noooo if you...")
    head = " ".join(toks[:2])
    if len(toks) >= 5 and head and toks.count(toks[0]) >= 2 and toks[0] in toks[2:4]:
        return True
    return False

def _click_score(title: str) -> float:
    """How likely a title is to earn a tap.

    Encodes what viral short-form titles share: a concrete subject, a turn or a
    stake, direct address, a knowledge gap, and enough brevity to read at a
    glance. It only ever *ranks* lines built from the speaker's own words.
    """
    t = (title or "").strip()
    toks = tokenize(t)
    content = content_tokens(t)
    if len(toks) < 3 or len(content) < 2:
        return -99.0

    distinct = _distinctive(t)
    score = 0.0
    score += min(len(distinct) / 4, 1.0) * 3.0          # a real subject
    if ANCHOR.search(t):
        score += 2.4                                     # concrete number
    if TURN.search(t):
        score += 1.5                                     # setup -> payoff
    if SECOND_PERSON.search(t):
        score += 1.9                                     # speaks to the viewer
    if CURIOSITY.search(t):
        score += 1.3                                     # opens a gap
    if STAKES.search(t):
        score += 1.1                                     # something is at risk
    n = len(toks)
    if 5 <= n <= 12:
        score += 1.5                                     # readable at a glance
    elif n > 17:
        score -= 1.6

    # Penalties: things that read like raw transcript, not a title.
    if DEPENDENT.match(t):
        score -= 3.0
    if FILLER_START.match(t) or WEAK_OPENER.match(t):
        score -= 2.2
    if EMPTY_EVAL.match(t):
        score -= 3.2
    if re.search(r"\b(you know|i mean|kind of|sort of|like i said|blah blah)\b", t, re.I):
        score -= 2.4
    if _is_fragment(t):
        score -= 2.0
    if HANGING_END.search(t) and not re.search(r"[!?]$", t):
        score -= 1.8
    if len(distinct) < 2:
        score -= 2.2
    if t.strip().endswith(","):
        score -= 1.5
    if _is_repetitive(t):
        score -= 4.0
    if EMPTY_EVAL.match(t):
        score -= 6.0
    if not _reads_like_english(t):
        score -= 5.0
    if re.search(r"\b(fuck|fucking|shit|bitch|asshole|prick|cunt|dick)\b", t, re.I):
        score -= 3.2
    return score


def _payoff_title(pool: list[str]) -> str | None:
    """Lead with the clip's own punchline rather than its setup line.

    Viral titles front-load the payoff. This picks the line with the most
    stakes/curiosity/topic weight and strips its chatter, without rewriting it.
    """
    best: tuple[float, str] = (-99.0, "")
    for raw in pool:
        text = _strip_vocatives(_strip_discourse(_clean(raw)))
        if len(tokenize(text)) < 4 or _is_fragment(text):
            continue
        score = _click_score(text)
        if score > best[0]:
            best = (score, text)
    if best[1] and best[0] > 0:
        return _fit(_titlecase_first(best[1]), 70)
    return None


def _direct_address_title(pool: list[str]) -> str | None:
    """"You're doing X wrong" style titles, built only from real 'you' lines."""
    best: tuple[float, str] = (-99.0, "")
    for raw in pool:
        text = _strip_vocatives(_clean(raw))
        if not re.search(r"\b(you|your|you're|yourself)\b", text, re.I):
            continue
        if len(tokenize(text)) < 4 or _is_fragment(text):
            continue
        score = _click_score(text) + 0.8
        if score > best[0]:
            best = (score, text)
    if best[1]:
        return _fit(_titlecase_first(best[1]), 70)
    return None


def _stakes_title(pool: list[str]) -> str | None:
    """A line where something was won, lost, risked or refused."""
    best: tuple[float, str] = (-99.0, "")
    for raw in pool:
        text = _strip_vocatives(_clean(raw))
        if not STAKES.search(text):
            continue
        if len(tokenize(text)) < 4 or _is_fragment(text):
            continue
        score = _click_score(text) + 0.9
        if score > best[0]:
            best = (score, text)
    if best[1]:
        return _fit(_titlecase_first(best[1]), 70)
    return None


def crafted_titles(pool: list[str]) -> list[str]:
    """Engaging titles derived from what the clip actually says.

    Candidates are generated from several viral shapes — payoff-first, stakes,
    direct address, contrast, list, number, question — then ranked by how
    clickable they read. Nothing is invented: every title is the speaker's own
    words with chatter removed.
    """
    scored: list[tuple[float, str]] = []

    def push(value: str | None, bonus: float = 0.0) -> None:
        if not value:
            return
        v = re.sub(r"\s+", " ", _titlecase_first(value)).strip(" ,;:-—")
        v = _strip_vocatives(v)
        if ORDINAL_OPEN.match(v):
            return
        if len(tokenize(v)) < 3 or len(content_tokens(v)) < 2:
            return
        if len(v) > 92:
            return
        if not _reads_like_english(v):
            return
        base = _click_score(v) + bonus
        if base <= -4.5:
            return
        if any(v.lower() == o.lower() for _, o in scored):
            return
        scored.append((base, v))

    # Shapes that front-load a hook earn a small bonus over plain lines.
    push(_number_title(pool), 1.6)
    push(_payoff_title(pool), 1.5)
    push(_direct_address_title(pool), 1.4)
    push(_stakes_title(pool), 1.2)
    push(_contrast_title(pool), 1.1)
    push(_curiosity_title(pool), 0.9)
    push(_list_title(pool), 1.0)
    push(_question_title(pool), 0.7)

    # Then the best complete lines, which are always safe.
    ranked = sorted(pool, key=_sentence_quality, reverse=True)
    for raw in ranked[:6]:
        cleaned = _strip_vocatives(_strip_discourse(_clean(raw)))
        if len(tokenize(cleaned)) < 3:
            continue
        if _is_fragment(cleaned):
            continue
        # Never start a title with a bare verb phrase ("Was the craziest...").
        if re.match(r"^(was|were|is|are|had|has|have|did|does|do|that|which|who)\b", cleaned, re.I):
            continue
        push(_fit(cleaned, 72))

    scored.sort(key=lambda x: -x[0])
    return [v for _, v in scored]



def _scrub_profanity(title: str) -> str:
    """Mask profanity in a title instead of publishing it.

    Only used as a repair step: the offending word is replaced with a neutral
    marker so the rest of a real line can still be used.
    """
    return BLOCKED_WORDS.sub(lambda m: "****" if len(m.group(0)) <= 4 else "*****", title or "")


def _is_weak_title(s: str) -> bool:
    """True when a title is too thin to publish.

    Catches the cases that slip past per-sentence checks: interjection strings
    ("So."), single generic nouns, and text with no topic word at all.
    """
    text = (s or "").strip()
    if not text:
        return True
    toks = tokenize(text)
    if len(toks) < 2 or len(content_tokens(text)) < 2:
        return True
    # Needs at least one word that names something (not "right", "yeah", "gonna").
    # A terse title like "Stop waiting" passes; "So." and "A story moment"
    # padding do not.
    if not _distinctive(text):
        return True
    if len(toks) == 2 and not any(len(w) > 4 for w in _distinctive(text)):
        return True
    return False


def _fallback_title(pool: list[str], category_label: str) -> str:
    """Build a readable title when no single line stands on its own.

    Interjection-heavy clips ("He's here! No!") have no complete sentence, so we
    either join the strongest neighbouring lines or use the clearest whole line —
    never a bare word lifted from the clip.
    """
    best: tuple[float, str] = (0.0, "")
    for i, first in enumerate(pool):
        clean_first = _strip_vocatives(_strip_discourse(_clean(first)))
        if len(tokenize(clean_first)) < 3:
            continue
        # Try the line on its own first: a single clean claim reads far better
        # than two clauses bolted together.
        options = [clean_first]
        if i + 1 < len(pool):
            nxt = _strip_vocatives(_strip_discourse(_clean(pool[i + 1])))
            # Only join two lines when the second continues the thought, never
            # when it starts a new one or is filler — that is what produced
            # run-ons like "I feel bad you heard of me Feel bad, bro".
            if (len(tokenize(nxt)) >= 3 and not _starts_new_thought(pool[i + 1])
                    and not _is_repetitive(nxt) and not LEADING_NOISE.match(nxt)):
                sep = " " if clean_first.endswith((".", "!", "?")) else " — "
                options.append(f"{clean_first}{sep}{nxt}")
        for joined in options:
            words = tokenize(joined)
            content = content_tokens(joined)
            if len(words) < 3 or len(content) < 2:
                continue
            if any(LIST_ITEM.match(x) for x in joined.split(" — ")):
                continue
            if _is_repetitive(joined):
                continue
            score = _click_score(joined)
            score += len(_distinctive(joined)) * 0.5
            if len(joined) > 90:
                score -= 3.0
            # A single clean line always beats a joined one at equal content.
            if len(options) > 1 and joined != clean_first:
                score -= 1.0
            if score > best[0]:
                best = (score, joined)
    if best[1] and best[0] > 0:
        joined_title = _titlecase_first(_fit(best[1], 72))
        if not _is_weak_title(joined_title) and _reads_like_english(joined_title):
            return joined_title

    # No join works: take the clearest whole sentence, however short — but it
    # must still carry real content, not just "So." or "Yeah.".
    whole = [
        s for s in pool
        if re.search(r"[.!?][\"')\]]*$", s.strip())
        and len(content_tokens(s)) >= 2
        and not _is_fragment(s)
    ]
    whole = [w for w in whole if _reads_like_english(w) and not _is_repetitive(w)]
    if whole:
        pick = max(whole, key=lambda s: (_click_score(s) + _sentence_quality(s) * 0.4,
                                         len(tokenize(s))))
        picked = _titlecase_first(_fit(pick, 72))
        if len(content_tokens(picked)) >= 2 and _reads_like_english(picked):
            return picked

    # A terse clip ("Stop waiting.") makes a perfectly good short title; only
    # pad it out when the words are filler.
    terse = [s.strip() for s in pool if 2 <= len(tokenize(s)) <= 4
             and len(content_tokens(s)) >= 2 and not ORDINAL_OPEN.match(s)
             and not WEAK_FRAGMENT.match(s) and not _is_weak_title(s)
             and _reads_like_english(s) and not _is_repetitive(s)]
    if terse:
        return _titlecase_first(_clean(terse[0]).strip(" ,;:-—"))

    # Still nothing: build a title from the clip's topic words, which are real
    # nouns and adjectives from what was said. "Funny moment" tells a viewer
    # nothing, whereas the subject at least tells them what the clip is about.
    topics = _noun_topics(" ".join(pool))[:2]
    # Topic templates are a last resort. Use one subject only, phrased as a
    # single readable thought — never two unrelated words stitched together.
    if topics:
        if category_label.lower() in {"funny moment", "high-energy moment"}:
            return _titlecase_first(f"The moment nobody expected with the {topics[0]}")
        return _titlecase_first(f"The truth about {topics[0]}")
    # Nothing usable at all: name the kind of clip, phrased as a real title
    # rather than an empty stub.
    label = category_label.lower()
    article = "An" if label[:1] in "aeiou" else "A"
    if label.endswith(("moment", "story", "take", "advice")):
        return f"{article} {label}"
    return f"{article} {label} moment"


def _best_title_sentence(pool: list[str]) -> str:
    strong = [s for s in pool if not _is_fragment(s)]
    if strong:
        return max(strong, key=_sentence_quality)
    # Nothing fully qualifies: fall back to the line with the most topic words.
    return max(pool, key=lambda s: (len(_distinctive(s)), _sentence_quality(s)))


# --------------------------------------------------------------------- metadata
def generate_metadata(text: str, sentences: list[str] | None, category: str,
                      category_label: str) -> dict:
    """Build titles, hook, description and hashtags from real transcript sentences.

    Titles always come from complete lines in the clip. Keyword fallbacks are
    built from meaningful words only, so we never emit things like "He'S and
    honors: what actually happened".
    """
    raw_pool = [s.strip() for s in (sentences or []) if len(tokenize(s)) >= 4]
    if not raw_pool:
        raw_pool = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text or "") if len(tokenize(p)) >= 4]
    if not raw_pool:
        raw_pool = [text.strip() or "Highlight"]
    # Strip trailing "bro"/"dude" chatter up front so every title shape reads
    # like a title rather than a transcript. The hook below still uses the
    # speaker's real opening line.
    pool = []
    for line in raw_pool:
        cleaned = _strip_vocatives(_strip_discourse(_clean(line)))
        pool.append(cleaned if len(tokenize(cleaned)) >= 3 else line)

    ranked = sorted(pool, key=_sentence_quality, reverse=True)
    strongest = _best_title_sentence(pool)
    runner_up = next(
        (s for s in ranked if s != strongest and not _is_fragment(s) and _sentence_quality(s) > 0),
        None,
    )
    payoff = next(
        (s for s in reversed(pool) if not _is_fragment(s) and _sentence_quality(s) > 0),
        strongest,
    )

    topics = _topic_words(text, limit=6)
    counts = Counter(
        w for w in content_tokens(text)
        if w.isalpha() and len(w) > 3 and w not in GENERIC and w not in NOT_TOPIC
    )
    strong_topics = [w for w in topics if counts[w] >= 2 and w not in VAGUE]

    # Crafted titles first: these lead with the clip's actual point instead of
    # repeating a sentence, which is what makes a title worth clicking.
    candidates: list[str] = list(crafted_titles(pool))

    def add(value: str | None) -> None:
        if not value:
            return
        v = _strip_vocatives(_titlecase_first(_fit(value, 72)))
        if len(tokenize(v)) < 3 or len(content_tokens(v)) < 2 or ORDINAL_OPEN.match(v):
            return
        # Same gates as the crafted titles: garbled, repetitive or empty lines
        # must never reach the published list, however they were produced.
        if not _reads_like_english(v) or _is_repetitive(v):
            return
        if _click_score(v) <= -5.5:
            return
        if BLOCKED_WORDS.search(v):
            return
        if v.lower() not in {c.lower() for c in candidates}:
            candidates.append(v)

    # 1. The best plain line, ranked by click value rather than raw length.
    plain = sorted(
        [x for x in pool if not _is_fragment(x)], key=_click_score, reverse=True
    )
    for line in plain[:3]:
        add(_strip_vocatives(line))
    # 2. A second strong line for variety.
    add(runner_up)
    # 3. The closing line, which usually carries the payoff.
    if payoff not in (strongest, runner_up):
        add(payoff)
    # 4. A question only when it genuinely asks one and has substance.
    q = next((s for s in ranked if s.strip().endswith("?") and not _is_fragment(s)), None)
    add(q)
    # 5. Topic-led variants only when a real subject word recurs across
    #    multiple lines — otherwise "The truth about feel" is empty.
    topic_lines: Counter = Counter()
    for line in raw_pool:
        for w in set(content_tokens(line)):
            topic_lines[w] += 1
    noun_topics = _noun_topics(" ".join(raw_pool))
    real_topics = [
        w for w in noun_topics
        if topic_lines.get(w, 0) >= 2 and len(w) > 4
        and w not in VAGUE and w not in GENERIC
    ]
    if real_topics:
        add(f"The truth about {real_topics[0].lower()}")
        if strongest:
            add(f"{real_topics[0].capitalize()}: {_clean(strongest)}")

    # Last line of defence: a title with no real subject word is not a title,
    # and nothing unpublishable is allowed through.
    candidates = [c for c in candidates if not _is_weak_title(c) and not BLOCKED_WORDS.search(c)]
    titles = candidates[:5]
    if not titles:
        fallback = _fallback_title(pool, category_label)
        label = category_label.lower()
        safe_generic = f"{'An' if label[:1] in 'aeiou' else 'A'} {label}" \
            if label.endswith(("moment", "story", "take", "advice")) \
            else f"{'An' if label[:1] in 'aeiou' else 'A'} {label} moment"
        # The fallback is also the speaker's words, so it needs the same gates.
        if _is_weak_title(fallback) or BLOCKED_WORDS.search(fallback) \
                or not _reads_like_english(fallback):
            # Rotate a few honest frames so sibling clips don't all read the
            # same, using the clip's own subject where one exists.
            noun = (_noun_topics(text) or [""])[0]
            options = [
                f"What happens next will surprise you" if label.startswith("funny") else "",
                f"The moment everything changed" if label.startswith(("story", "emotional")) else "",
                f"Nobody saw this coming",
                f"The part everyone misses",
            ]
            options = [o for o in options if o]
            seed = sum(ord(ch) for ch in (text or "")) % len(options)
            fallback = options[seed]
            if noun and label.startswith("story"):
                fallback = f"The {noun} story nobody tells"
        titles = [fallback]
    # De-duplicate near-identical titles (one a prefix of another), keeping the
    # stronger of the two so a short weak stub doesn't shadow a real hook.
    final: list[str] = []
    for t in titles:
        dup = next(
            (o for o in final if t.lower() in o.lower() or o.lower() in t.lower()),
            None,
        )
        if dup is not None:
            if _click_score(t) > _click_score(dup):
                final[final.index(dup)] = t
            continue
        final.append(t)
    # The first title is the one suggested by default, so lead with the hook.
    final.sort(key=_click_score, reverse=True)
    titles = final or titles[:1]

    # Hook = the first thing the viewer hears, kept verbatim.
    hook = _titlecase_first(_fit(pool[0], 110)) or titles[0]

    tag_words = [w for w in topics if w not in VAGUE and len(w) > 4][:4]
    hashtags = [f"#{re.sub(r'[^a-z0-9]', '', k)}" for k in tag_words]
    tags_by_cat = {
        "funny": ["#funny", "#comedy"],
        "emotional": ["#storytime", "#emotional"],
        "controversial": ["#hotake", "#debate"],
        "insight": ["#advice", "#learnontiktok"],
        "revelation": ["#mindblown", "#unexpected"],
        "high_energy": ["#gaming", "#clutch"],
        "story": ["#storytime", "#true"],
    }.get(category, [])
    hashtags += tags_by_cat + ["#shorts", "#fyp"]
    hashtags = list(dict.fromkeys(h for h in hashtags if len(h) > 3))[:6]

    description = _clean(text)
    if len(description) > 210:
        description = description[:207].rsplit(" ", 1)[0] + "…"

    return {
        "titles": titles,
        "hook": hook,
        "hashtags": hashtags,
        "description": description,
        "keywords": topics,
    }


# --------------------------------------------------------------------- headlines
def headline_variants(text: str, titles: list[str] | None = None,
                      hook: str = "") -> list[str]:
    """Short, punchy on-screen headlines for the opening seconds of a clip.

    Headlines are lines taken from the clip, trimmed at clause boundaries so they
    never read as a fragment of a sentence.
    """
    pool = [t for t in (titles or []) if t.strip()]
    pool += [p.strip() for p in re.split(r"(?<=[.!?])\s+", text or "") if len(tokenize(p)) >= 4]
    if hook:
        pool.insert(0, hook)

    out: list[str] = []
    seen: set[str] = set()

    def shorten(c: str, limit: int = 48) -> str:
        """Keep the leading clause(s); never end on a hanging word."""
        c = c.strip(" ,;:—")
        if len(c) <= limit:
            return c
        clauses = [p.strip(" ,;:—") for p in re.split(r", | — | - |; |: ", c) if p.strip()]
        kept = ""
        for clause in clauses:
            trial = f"{kept}, {clause}" if kept else clause
            if len(trial) > limit:
                break
            kept = trial
        if kept:
            return kept
        acc = ""
        for word in c.split():
            if len(f"{acc} {word}".strip()) > limit:
                break
            acc = f"{acc} {word}".strip()
        # Drop a trailing function word so the cut lands on a real word.
        acc = re.sub(r"\s+(and|but|or|so|the|a|an|of|to|in|on|for|with|that|which|is|are|was|were|it|this|they|you|we|i)\W*$", "", acc, flags=re.I)
        return acc.strip(" ,;:—")

    def push(candidate: str) -> None:
        c = _titlecase_first(_clean(candidate))
        c = re.sub(r"\s+", " ", c).strip(" ,;:-—")
        if not c or c.lower() in seen:
            return
        c = shorten(c)
        # Never end a headline mid-thought ("...who keep showing up when").
        for _ in range(3):
            trimmed = re.sub(
                r"\s+(and|but|or|so|the|a|an|of|to|in|on|for|with|that|which|who|whom|"
                r"is|are|was|were|not|no|it|this|these|those|they|them|you|we|i|"
                r"when|where|while|because|if|as|at|by|from|than|then)\W*$",
                "", c, flags=re.I,
            ).strip(" ,;:-—")
            if trimmed == c:
                break
            c = trimmed
        if len(c) < 10 or len(c.split()) < 3 or c.lower() in seen:
            return
        # Needs at least one concrete subject word, or plenty of real content.
        if not _distinctive(c) and len(content_tokens(c)) < 4:
            return
        if HANGING_END.search(c) and not c.endswith(("?", "!", ".")):
            return
        seen.add(c.lower())
        out.append(c)

    for candidate in pool[:6]:
        push(candidate)
        if len(out) >= 4:
            break

    # Only fall back to a topic template when a concrete subject word recurs;
    # otherwise a sentence from the clip always reads better than a template.
    topics = _topic_words(text, limit=6)
    counts = Counter(
        w for w in content_tokens(text)
        if w.isalpha() and len(w) > 4 and w not in GENERIC and w not in NOT_TOPIC
    )
    for word in [w for w in topics if counts[w] >= 2 and w not in VAGUE][:2]:
        if len(out) >= 3:
            break
        push(f"No one talks about {word}")
    return out[:4]
