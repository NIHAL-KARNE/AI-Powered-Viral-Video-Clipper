"""Regression tests for keyword highlighting and auto emoji.

Run: cd backend && .venv/bin/python test_emphasis.py
"""
from __future__ import annotations

import sys

from app import emphasis
from app.render import build_ass, caption_chunks, word_captions

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def cue(words: list[str], start: float = 0.0, step: float = 0.3) -> dict:
    return {
        "start": start,
        "end": start + step * len(words),
        "active": None,
        "words": [
            {"start": start + i * step, "end": start + (i + 1) * step, "word": w}
            for i, w in enumerate(words)
        ],
    }


def main() -> int:
    print("keyword highlighting")

    # A stake word is accented.
    flags = emphasis.highlight_words(cue(["I", "lost", "a", "million"]).get("words"))
    check("stake word highlighted", flags[1] or flags[3], str(flags))

    # Filler is never accented.
    flags = emphasis.highlight_words(cue(["you", "want", "to", "know"]).get("words"))
    check("filler not highlighted", not any(flags), str(flags))

    # Phrases are accented as a unit: "feel bad" is the point of the line.
    flags = emphasis.highlight_words(cue(["I", "feel", "bad,"]).get("words"))
    check("phrase highlighted as a unit", flags[1] and flags[2], str(flags))

    # Numbers are concrete and get accented.
    flags = emphasis.highlight_words(cue(["only", "60", "dollars"]).get("words"))
    check("number highlighted", flags[1], str(flags))

    print("auto emoji")

    # A cue with no emotion gets no emoji, rather than a random one.
    check("no emoji on neutral line", emphasis.cue_emoji("you want to know") is None)
    check("no emoji on filler", emphasis.cue_emoji("okay") is None)

    # Emotion maps to a fitting emoji.
    check("laughter maps to laughing", emphasis.cue_emoji("that is so funny") == "😂",
          str(emphasis.cue_emoji("that is so funny")))
    check("money maps to money", emphasis.cue_emoji("I made a million dollars") == "💰")
    check("fear maps to fear", emphasis.cue_emoji("I was so scared") == "😱")

    # Low-signal words no longer fire. "time" alone used to produce a clock.
    check("plain 'time' does not fire", emphasis.cue_emoji("every time you talk") is None,
          str(emphasis.cue_emoji("every time you talk")))

    print("emoji planning")

    cues = [cue(["I", "feel", "bad,"], 0.0), cue(["you", "want", "to"], 1.0),
            cue(["that", "is", "so", "funny"], 2.0), cue(["okay"], 3.5)]
    plan = emphasis.plan_emoji(cues)
    indices = [p["index"] for p in plan]
    check("plan is non-empty", bool(plan), str(plan))
    check("plan is sorted", indices == sorted(indices), str(indices))
    check("no emoji on filler cue", 3 not in indices, str(indices))
    check("no duplicate cues", len(indices) == len(set(indices)), str(indices))

    # An emoji is anchored to the cue that holds the trigger word, not the cue
    # the search window started in.
    cues = [cue(["them."], 0.0), cue(["I", "feel", "bad,"], 0.5), cue(["bro"], 1.6)]
    plan = emphasis.plan_emoji(cues)
    check("anchored to trigger cue", plan and plan[0]["index"] == 1, str(plan))

    # A neutral clip gets nothing at all.
    check("neutral clip gets no emoji",
          emphasis.plan_emoji([cue(["we", "walked", "down", "the", "road"], 0.0)]) == [])

    print("caption length")

    # Default cue is 4-5 words, not 3: three-word cues flash past unreadably.
    words = [{"start": i * 0.32, "end": i * 0.32 + 0.3, "word": w}
             for i, w in enumerate("I think I got a hug them and then I feel bad".split())]
    chunks = caption_chunks(words, 5)
    lengths = [len(c) for c in chunks]
    check("default cue length is 4-5", max(lengths) <= 5 and min(lengths) >= 3, str(lengths))
    check("fewer cues than 3-word chunking",
          len(chunks) < len(caption_chunks(words, 3)), f"{len(chunks)}")

    # A larger setting genuinely produces longer lines.
    long_chunks = caption_chunks(words, 7)
    check("7-word setting makes longer cues",
          max(len(c) for c in long_chunks) > max(lengths), str([len(c) for c in long_chunks]))

    # A cue never ends on a dangling function word.
    hard = "the a an to of and but or for with in on at my your is are that".split()
    bad = [c for c in caption_chunks(words, 4) if c and c[-1]["word"].strip().strip(".,!?").lower() in hard]
    check("no cue ends on a function word", not bad,
          str([[w["word"] for w in c] for c in bad]))

    # Sentence punctuation always breaks the cue, even when short.
    punct = [{"start": i * 0.3, "end": i * 0.3 + 0.28, "word": w}
             for i, w in enumerate("Run! I could not believe it happened".split())]
    first = caption_chunks(punct, 6)[0]
    check("sentence end breaks the cue", first[-1]["word"].endswith("!"),
          " ".join(w["word"] for w in first))

    # The length setting reaches the real cue builder.
    c2 = word_captions(words, 0, 10, "bold-pop", max_words=7)
    check("word_captions honours max_words", len(c2[0]["words"]) >= 5,
          str(len(c2[0]["words"])))

    print("render integration")

    # The subtitle file carries the keyword colour but only when enabled.
    c = cue(["I", "lost", "a", "million"], 0.0)
    from pathlib import Path
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    on = build_ass([c], "bold-pop", tmp / "on.ass", 1080, 1920, "bottom")
    off = build_ass([c], "bold-pop", tmp / "off.ass", 1080, 1920, "bottom",
                    keywords_enabled=False)
    on_text = [l for l in on.read_text().splitlines() if l.startswith("Dialogue")][0]
    off_text = [l for l in off.read_text().splitlines() if l.startswith("Dialogue")][0]
    keyword_colour = "&H004DE1FF"
    check("keyword colour present when enabled", on_text.count(keyword_colour) >= 1, on_text[-90:])
    check("keyword colour absent when disabled", keyword_colour not in off_text, off_text[-90:])

    # Cues still build from real words, so the toggles act on real captions.
    words = [{"start": i * 0.4, "end": i * 0.4 + 0.35, "word": w}
             for i, w in enumerate("I lost a million dollars today folks".split())]
    built = word_captions(words, 0, 3, "bold-pop")
    check("cues built from words", len(built) >= 2, str(len(built)))

    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
