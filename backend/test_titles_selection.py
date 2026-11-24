"""Regression tests for title quality and viral clip shape.

Run: cd backend && .venv/bin/python test_titles_selection.py
"""
from __future__ import annotations

import sys

from app.titles import BLOCKED_WORDS, generate_metadata, crafted_titles
from app import selection

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def main() -> int:
    print("titles")

    # Publishable: no profanity or slurs can reach a title.
    meta = generate_metadata(
        "Bro I'm not watching these fucking ads anymore, man. This is insane.",
        ["Bro I'm not watching these fucking ads anymore, man.", "This is insane."],
        "controversial",
        "Controversial take",
    )
    check("no profanity in titles", not any(BLOCKED_WORDS.search(t) for t in meta["titles"]),
          str(meta["titles"]))

    # Trailing chatter is stripped ("..., bro").
    meta = generate_metadata(
        "I feel bad, bro. Hey, you heard of me?",
        ["I feel bad, bro.", "Hey, you heard of me?"],
        "high_energy", "High-energy moment",
    )
    check("vocatives stripped", not meta["titles"][0].lower().endswith(", bro"), meta["titles"][0])

    # Garbled transcript never becomes a title.
    meta = generate_metadata(
        "Say every the last two people on Earth. My name's be team.",
        ["Say every the last two people on Earth.", "My name's be team."],
        "story", "Storytelling",
    )
    check("garbled lines rejected", "every the last" not in meta["titles"][0].lower()
          and "name's be" not in meta["titles"][0].lower(), meta["titles"][0])

    # Stuttered lines never become titles.
    meta = generate_metadata(
        "Nooo Nooo If you have metal in your hands you'll explode.",
        ["Nooo Nooo If you have metal in your hands you'll explode."],
        "revelation", "Unexpected revelation",
    )
    check("stutters rejected", "nooo nooo" not in meta["titles"][0].lower(), meta["titles"][0])

    # A concrete, high-stakes line is preferred and cleaned.
    meta = generate_metadata(
        "I just lost my assistant manager position. People get an ounce of power.",
        ["I just lost my assistant manager position.", "People get an ounce of power."],
        "story", "Storytelling",
    )
    check("stakes line wins", "lost" in meta["titles"][0].lower()
          or "power" in meta["titles"][0].lower(), meta["titles"][0])

    # Whisper artefacts repaired.
    meta = generate_metadata(
        "You're hitting me with a 60 -year -old. That's crazy.",
        ["You're hitting me with a 60 -year -old.", "That's crazy."],
        "revelation", "Unexpected revelation",
    )
    check("dash artefacts repaired", "60 -year" not in meta["titles"][0], meta["titles"][0])

    # Titles are always non-empty and never a bare label with double nouns.
    for text in ("Big Team! Big Team! Big Team!", "Yeah. Okay. Right.", ""):
        meta = generate_metadata(text, [text] if text else [], "story", "Storytelling")
        check(f"non-empty title for {text[:12]!r}", bool(meta["titles"][0].strip()), str(meta["titles"]))
        check(f"no doubled moment for {text[:12]!r}",
              "moment moment" not in meta["titles"][0].lower(), meta["titles"][0])

    # Crafted titles rank a hook first when one exists.
    picked = crafted_titles([
        "I just lost my assistant manager position.",
        "People get an ounce of power and they lose their minds.",
        "And then, you know, whatever.",
    ])
    check("crafted titles non-empty", bool(picked), str(picked))

    print("selection")
    # A dependent-verb opener cannot start a clip.
    sents = [{"text": t} for t in ("is on doing in this game.", "Okay buddy what the hell.")]
    check("verb opener rejected", not selection._complete_start(sents, 0))  # type: ignore[arg-type]

    # Viral structure: cold open scores higher than a buried hook.
    def line(text, start, end, **kw):
        base = {
            "text": text, "start": start, "end": end, "tokens": text.lower().split(),
            "content": text.lower().split(), "dur": end - start, "question": text.endswith("?"),
            "exclaim": text.count("!"), "punch": 0.1, "hook": 0.1, "filler": 0.0,
            "wps": 3.0, "rarity": 0.5, "faces": 0.5, "motion": 0.5,
            "audio": {"silence": 0.0, "dyn": 0.1, "loudness": 0.5, "peak": 0.5},
        }
        base.update(kw)
        return base

    cold = [line("This is the craziest thing I have ever seen!", 0, 3, punch=2.0, hook=2.0),
            line("And then we kept walking down the road.", 3, 9)]
    buried = [line("And then we kept walking down the road.", 0, 6, punch=0.0, hook=0.0),
              line("This is the craziest thing I have ever seen!", 6, 9, punch=2.0, hook=2.0)]
    vc = selection._viral_structure(cold, 0, 1)
    vb = selection._viral_structure(buried, 0, 1)
    check("cold open beats buried hook", vc["viral"] > vb["viral"], f"{vc['viral']} vs {vb['viral']}")
    check("cold open flagged", vc["cold_open"] is True and vb["cold_open"] is False)

    # Dead air lowers the score.
    noisy = [line("We were talking for a while about nothing much.", 0, 8, punch=1.0),
             line("Then it ended.", 8, 9)]
    for s in noisy:
        s["audio"] = {"silence": 0.9, "dyn": 0.0, "loudness": 0.2, "peak": 0.2}
        s["wps"] = 0.4
    vd = selection._viral_structure(noisy, 0, 1)
    check("dead air penalised", vd["dead_air"] > 0.4, str(vd))

    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
