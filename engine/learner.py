"""Pattern-recognition layer: learns which clip choices earn views.

What it learns (Beta-Bernoulli Thompson sampling, one arm per option):
  hook template · duration bucket · streamer/source · posting hour slot
"Success" for a posted clip = its 48h views beat the running median of our own
posts (adaptive bar, so it keeps pushing toward the top half as the channel grows).

Market prior: once a day it scans the top GTA 6 Shorts of the last 72h via the
YouTube Data API (read-only key, free) and nudges duration and keyword priors
toward what is currently winning in the wider market.

All state lives in state/learner.json so it survives between runs.
"""
import json, math, random, re, time
from collections import Counter
from pathlib import Path
import requests
from .util import ROOT

STATE = ROOT / "state" / "learner.json"
DUR_BUCKETS = ["<20", "20-30", "30-45", "45-60", "60+"]
SLOTS = ["morning", "midday", "evening", "late"]


def bucket(seconds):
    for lim, name in ((20, "<20"), (30, "20-30"), (45, "30-45"), (60, "45-60")):
        if seconds < lim:
            return name
    return "60+"


def slot(hour):
    return "morning" if 5 <= hour < 11 else "midday" if hour < 16 else "evening" if hour < 21 else "late"


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    s = {"arms": {}, "views": [], "hashes": [], "trend_terms": [], "last_scan": 0}
    # research-based priors (streamer/GTA clip guides): 20-45s performs best on Shorts
    for b, (a, bb) in {"20-30": (3, 2), "30-45": (3, 2), "45-60": (2, 2), "<20": (1, 2),
                       "60+": (1, 2)}.items():
        s["arms"][f"dur:{b}"] = [a, bb]
    return s


def save(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def _arm(s, key):
    return s["arms"].setdefault(key, [1.0, 1.0])


def sample(s, key, rng=random):
    a, b = _arm(s, key)
    return rng.betavariate(a, b)


def choose(s, prefix, options, rng=random):
    """Thompson pick among options for one dimension."""
    return max(options, key=lambda o: sample(s, f"{prefix}:{o}", rng))


def expected_value(s, job, rng=random):
    """Sampled success probability for a candidate clip (product of dimensions)."""
    keys = [f"hook:{job['hook_id']}", f"dur:{bucket(job['render']['duration'])}",
            f"src:{job.get('streamer') or 'unknown'}"]
    p = 1.0
    for k in keys:
        p *= sample(s, k, rng)
    strength = 1 / (1 + math.exp(-(job["highlight"]["score"] - 1.5)))  # detection confidence
    return p ** (1 / len(keys)) * (0.5 + strength)


def record_outcome(s, job, views48):
    """Update all arms the clip touched once its 48h view count is known."""
    s["views"].append(views48)
    s["views"] = s["views"][-300:]
    med = sorted(s["views"])[len(s["views"]) // 2]
    win = views48 > med if len(s["views"]) >= 5 else views48 >= 1000
    hour = int(job.get("scheduled_for", "T12")[11:13] or 12)
    for k in (f"hook:{job['hook_id']}", f"dur:{bucket(job['render']['duration'])}",
              f"src:{job.get('streamer') or 'unknown'}", f"slot:{slot(hour)}"):
        a = _arm(s, k)
        a[0 if win else 1] += 1
    return win


def remember_hash(s, h):
    s["hashes"].append(h)
    s["hashes"] = s["hashes"][-2000:]


# ---------- market scan ----------
def _iso_dur(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def market_scan(s, api_key, query="GTA 6", hours=72, every_s=20 * 3600):
    if not api_key or time.time() - s.get("last_scan", 0) < every_s:
        return None
    after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    r = requests.get("https://www.googleapis.com/youtube/v3/search", params={
        "part": "snippet", "q": query + " #shorts", "type": "video", "videoDuration": "short",
        "order": "viewCount", "publishedAfter": after, "maxResults": 50, "key": api_key},
        timeout=30).json()
    ids = [i["id"]["videoId"] for i in r.get("items", [])]
    if not ids:
        return None
    v = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
        "part": "statistics,contentDetails,snippet", "id": ",".join(ids), "key": api_key},
        timeout=30).json()
    rows = []
    for it in v.get("items", []):
        views = int(it["statistics"].get("viewCount", 0))
        age_h = max(1.0, (time.time() - time.mktime(time.strptime(
            it["snippet"]["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S"))) / 3600)
        rows.append({"title": it["snippet"]["title"], "dur": _iso_dur(it["contentDetails"]["duration"]),
                     "vph": views / age_h})
    rows.sort(key=lambda x: -x["vph"])
    top = rows[: max(5, len(rows) // 3)]
    # nudge duration priors toward the buckets winning right now (small pseudo-counts)
    for row in top:
        _arm(s, f"dur:{bucket(row['dur'])}")[0] += 0.3
    for row in rows[len(rows) // 2:]:
        _arm(s, f"dur:{bucket(row['dur'])}")[1] += 0.15
    words = Counter()
    stop = {"the", "a", "in", "of", "to", "and", "is", "this", "gta", "6", "vi", "shorts", "i",
            "you", "on", "for", "it", "my", "with", "be", "was", "that", "how", "what"}
    for row in top:
        for w in re.findall(r"[a-z][a-z']{2,}", row["title"].lower()):
            if w not in stop:
                words[w] += 1
    s["trend_terms"] = [w for w, c in words.most_common(12) if c >= 2]
    s["last_scan"] = time.time()
    return {"scanned": len(rows), "trend_terms": s["trend_terms"]}


def youtube_views(api_key, video_ids):
    if not api_key or not video_ids:
        return {}
    out = {}
    for i in range(0, len(video_ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
            "part": "statistics", "id": ",".join(video_ids[i:i + 50]), "key": api_key},
            timeout=30).json()
        for it in r.get("items", []):
            out[it["id"]] = int(it["statistics"].get("viewCount", 0))
    return out
