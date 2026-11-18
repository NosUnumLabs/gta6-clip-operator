"""Hook/title templates. Each has a stable id so the learner can score it.

Rules from research: titles under ~7 words, describe the situation (not the
punchline), make a curiosity gap the clip actually pays off, credit the streamer.
Templates are deliberately situation-generic so they stay truthful for any
reaction/chaos moment; the learner retires the ones that underperform.
"""
import random

HOOKS = {
    "streamer": {
        "s_notready": "{streamer} wasn't ready for this",
        "s_reaction": "{streamer}'s reaction to GTA 6 😭",
        "s_broke": "This GTA 6 moment broke {streamer}",
        "s_waitforit": "Wait for it… ({streamer} in GTA 6)",
        "s_chat": "Chat lost it at this part",
        "s_firsthour": "{streamer}'s first hours in GTA 6",
        "s_vicecity": "{streamer} vs Vice City",
        "s_whyyoudont": "This is why you don't do this in GTA 6",
        "s_rockstar": "Rockstar really added this 💀",
        "s_npcs": "GTA 6 NPCs are something else",
    },
    "chaos": {
        "c_cops": "Vice City cops do NOT play",
        "c_physics": "GTA 6 physics are insane",
        "c_waitforit": "Wait for it…",
        "c_notready": "I was NOT ready for this",
        "c_dont": "This is why you don't speed in Leonida",
    },
    "discovery": {
        "d_missed": "You missed this in GTA 6",
        "d_detail": "GTA 6 has a detail nobody noticed",
        "d_vs": "GTA 6 vs GTA 5 — look at this",
        "d_hidden": "Rockstar hid this in Vice City",
    },
}


def hook_ids(lane):
    return list(HOOKS.get(lane, HOOKS["streamer"]).keys())


def hook_text(lane, hook_id, streamer=""):
    t = HOOKS.get(lane, HOOKS["streamer"])[hook_id]
    if "{streamer}" in t and not streamer:
        t = t.replace("{streamer}'s", "His").replace("{streamer}", "He")
    return t.format(streamer=streamer)


def pick_hook(lane, rng=random):
    """Back-compat for manual mode: (text) of a random template."""
    hid = rng.choice(hook_ids(lane))
    return hook_text(lane, hid)


def caption(lane, hook, hashtags, streamer="", extra_terms=(), suffix="", rng=random):
    tags = list(hashtags)
    rng.shuffle(tags)
    credit = f"\n\n🎥 {streamer}" if streamer else ""
    trend = ""
    if extra_terms:
        trend = " " + " ".join("#" + t for t in list(extra_terms)[:2])
    tail = f"\n{suffix}" if suffix else ""
    return f"{hook}{credit}{tail}\n\n{' '.join(tags)}{trend}".strip()
