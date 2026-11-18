"""Editorial intelligence: turns a raw highlight window + transcript into a tight edit.

  snap_bounds    start on a sentence, end after the reaction (never mid-sentence)
  keep_segments  jump-cut dead air (> MAX_GAP s with no speech and low audio)
  pick_quote     the streamer's own words for the title/hook -> accurate by construction
  profanity      block unsafe clips, mask strong words in captions, keep titles clean
"""
import re

MAX_GAP = 1.1        # seconds of silence tolerated inside a clip
TAIL = 0.7           # keep a beat after the last word (the reaction lands here)
LEAD = 0.25          # tiny breath before the first word

# Hard block: slurs / explicit sexual content -> clip is rejected (platform + campaign safety)
_BLOCK = [r"\bn[i1]gg", r"\bf[a@]gg?ot", r"\bretard", r"\btr[a@]nny", r"\bk[i1]ke\b", r"\bsp[i1]c\b",
          r"\bch[i1]nk\b", r"\bporn", r"\bcum\b", r"\bblowjob", r"\bdick\b", r"\bpussy", r"\bboobs?\b"]
# Strong words: allowed in speech, masked in captions, never in titles/hooks
_MASK = [r"\bf+u+c+k\w*", r"\bsh[i1]t\w*", r"\bb[i1]tch\w*", r"\bass(hole)?\b", r"\bdamn\b",
         r"\bmotherf\w*", r"\bbastard\w*", r"\bcrap\b", r"\bhell\b"]
_BLOCK_RE = re.compile("|".join(_BLOCK), re.I)
_MASK_RE = re.compile("|".join(_MASK), re.I)

SPOILER_WORDS = re.compile(r"\b(dies?|died|death|dead|killed|kills?|ending|ends?|betray\w*|"
                           r"final mission|finale|twist|spoiler)\b", re.I)


def unsafe(text):
    return bool(_BLOCK_RE.search(text or ""))


def mask(word):
    return _MASK_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), word)


def has_strong(text):
    return bool(_MASK_RE.search(text or ""))


def sentences(words, gap=0.6):
    """Group (start, end, word) into utterances split on pauses or end punctuation."""
    out, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] > gap or re.search(r"[.!?]$", cur[-1][2])):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def snap_bounds(words, start, end, peak, min_len, max_len):
    """Move start back to the beginning of its utterance and end forward to the end of the
    utterance that contains (or follows) the peak, plus a reaction tail."""
    utts = sentences(words)
    if not utts:
        return start, end
    s = start
    for u in utts:
        if u[0][0] <= start <= u[-1][1] + 0.3:
            s = max(0.0, u[0][0] - LEAD)
            break
        if u[0][0] > start:
            s = max(0.0, u[0][0] - LEAD)
            break
    e = end
    after_peak = [u for u in utts if u[-1][1] >= peak]
    if after_peak:
        # finish the utterance that is running at the payoff, then hold for the reaction
        tgt = after_peak[0]
        for u in after_peak:
            if u[0][0] <= end + 1.0:
                tgt = u
        e = tgt[-1][1] + TAIL
    if e - s > max_len:  # too long: keep the payoff, drop setup
        s = max(s, e - max_len)
        first = next((u for u in utts if u[0][0] >= s), None)
        if first:
            s = max(0.0, first[0][0] - LEAD)
    if e - s < min_len:
        e = s + min_len
    return round(s, 2), round(e, 2)


def keep_segments(words, start, end, max_gap=MAX_GAP, loud=None):
    """Intervals to keep inside [start, end]: everything except silent gaps > max_gap.
    `loud(t0, t1)` (optional) returns True if the gap has game audio worth keeping."""
    ws = [w for w in words if w[1] > start and w[0] < end]
    if not ws:
        return [(start, end)]
    segs, cur_s = [], start
    prev_end = start
    for w in ws:
        gap = w[0] - prev_end
        if gap > max_gap and not (loud and loud(prev_end, w[0])):
            segs.append((cur_s, prev_end + 0.35))
            cur_s = w[0] - 0.2
        prev_end = max(prev_end, w[1])
    segs.append((cur_s, end))
    return [(round(a, 2), round(b, 2)) for a, b in segs if b - a > 0.3]


def remap(words, segs):
    """Shift word times onto the cut timeline produced by keep_segments."""
    out, offset = [], 0.0
    for a, b in segs:
        for s, e, w in words:
            if a <= s < b:
                out.append((round(s - a + offset, 3), round(min(e, b) - a + offset, 3), w))
        offset += b - a
    return out


def pick_quote(words, peak, max_words=8):
    """Choose a short, clean utterance near the peak to use verbatim as the hook/title."""
    best, best_score = None, -1e9
    for u in sentences(words):
        text = " ".join(w[2] for w in u).strip()
        n = len(u)
        if n < 2 or n > 12 or has_strong(text) or unsafe(text) or SPOILER_WORDS.search(text):
            continue
        dist = min(abs(u[0][0] - peak), abs(u[-1][1] - peak))
        score = (-dist + (1.5 if re.search(r"[!?]", text) else 0) + (1.0 if 3 <= n <= max_words else 0)
                 - (2.0 if n > max_words else 0))  # complete sentences beat truncated ones
        if score > best_score:
            best, best_score = text, score
    if not best:
        return None
    best = re.sub(r"\s+", " ", best).strip(" .,")
    words_ = best.split()
    if len(words_) > max_words:
        best = " ".join(words_[:max_words]) + "…"
    return best[0].upper() + best[1:]
