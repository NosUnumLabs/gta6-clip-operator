"""Campaign compliance overseer. Every clip gets a written checklist; one failed item = no post.

Rules come from each campaign's config entry (mirroring its brief) plus standing
platform/clipping rules. The checklist is saved on the job so any rejection is auditable.
"""
import datetime as dt
import re
from .edit import SPOILER_WORDS, has_strong, unsafe


def check(job, camp, acc, cfg, transcript_text, posted_today_for_campaign, other_campaign_hashes):
    q = cfg.get("quality", {})
    c = {}
    now = dt.datetime.now().astimezone()

    def ok(name, cond, why=""):
        c[name] = {"pass": bool(cond), "why": "" if cond else why}

    ok("platform_allowed", acc["platform"] in camp.get("platforms", []),
       f"{acc['platform']} not in campaign platforms")
    ok("campaign_window",
       (not camp.get("start_at") or now >= dt.datetime.fromisoformat(camp["start_at"])) and
       (not camp.get("end_at") or now <= dt.datetime.fromisoformat(camp["end_at"])),
       "outside campaign dates")
    ok("source_authorized", job.get("rights_ok"), "footage not from a campaign-named source")
    d = job["render"]["duration"]
    lo, hi = camp.get("min_clip_s", q.get("min_clip_s", 15)), camp.get("max_clip_s", q.get("max_clip_s", 60))
    ok("duration", lo <= d <= hi, f"{d:.1f}s outside {lo}-{hi}s")
    ok("captions_present", job.get("captions") and job.get("caption_words", 0) >= q.get("min_caption_words", 6),
       "no clean subtitles (too little detected speech)")
    ok("transcript_safe", not unsafe(transcript_text), "explicit or hateful language in clip")
    title = job.get("title", "")
    ok("title_clean", not has_strong(title) and not unsafe(title), "profanity in title")
    ok("no_spoiler_in_title", not SPOILER_WORDS.search(title + " " + job.get("hook", "")),
       "title/hook may reveal a story moment")
    if job.get("hook_kind") == "quote":
        quote = job["hook"].strip("“”\"' …").lower()
        ok("title_accurate", quote[:20] in transcript_text.lower(), "quoted title not found in transcript")
    else:
        ok("title_accurate", True)
    cap = job.get("caption", "")
    for tag in camp.get("required_hashtags", []):
        ok(f"hashtag {tag}", tag.lower() in cap.lower(), f"missing {tag}")
    for credit in camp.get("required_credit", []):
        ok(f"credit {credit}", credit.lower() in cap.lower(), f"missing credit '{credit}'")
    if camp.get("disclosure_required"):
        ok("disclosure_on_screen", bool(job.get("disclosure_rendered")), "no on-screen paid disclosure")
        ok("disclosure_in_caption", re.search(r"#ad\b|paid", cap, re.I), "no paid disclosure in caption")
    ok("unique_to_campaign", not job.get("dup_of_other_campaign"), "same moment already used for another campaign")
    cap_n = camp.get("max_posts_per_day", q.get("max_posts_per_campaign_per_day", 3))
    ok("daily_cap", posted_today_for_campaign < cap_n, f"already {posted_today_for_campaign}/{cap_n} today")
    ok("quality_floor", job.get("quality", 0) >= q.get("min_quality", 0.55),
       f"quality {job.get('quality', 0):.2f} below floor")
    return c, [f"{k}: {v['why']}" for k, v in c.items() if not v["pass"]]


def quality_score(highlight_score, words, duration, letterbox, avg_prob=None):
    """0..1 blend: highlight strength, speech density (captions carry the clip), confidence."""
    import math
    strength = 1 / (1 + math.exp(-(highlight_score - 1.5)))
    wps = len(words) / max(duration, 1)
    speech = min(1.0, wps / 1.6)            # ~1.6 words/s = talkative reaction
    conf = avg_prob if avg_prob is not None else 0.8
    penalty = 0.5 if letterbox > 0.3 else 0.0
    return round(max(0.0, 0.45 * strength + 0.35 * speech + 0.20 * conf - penalty), 3)
