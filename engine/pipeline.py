"""Ingest -> detect -> render per account -> pending queue -> review -> schedule."""
import datetime as dt, random, shutil
from pathlib import Path
from zoneinfo import ZoneInfo
from .util import new_id, write_json, read_json, log
from .detect import find_highlights
from .render import render_clip
from .hooks import pick_hook, caption

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".flv"}


def ingest(src, cfg, source_label="own_capture", campaign_id="own_channel", lanes=None):
    src = Path(src)
    clips, dur = find_highlights(src, cfg)
    log(cfg, f"[detect] {src.name}: {dur/60:.1f} min -> {len(clips)} highlights")
    accounts = [a for a in cfg["accounts"] if not lanes or a["lane"] in lanes]
    camp = next((c for c in cfg["campaigns"] if c["id"] == campaign_id), None)
    jobs = []
    for ci, clip in enumerate(clips):
        # round-robin highlights across accounts so each account gets different moments,
        # and the best moments go to more than one account (each with its own render)
        targets = accounts if ci < 2 else [accounts[ci % len(accounts)]]
        for acc in targets:
            if camp and acc["platform"] not in camp["platforms"]:
                continue
            jid = new_id()
            hook = pick_hook(acc["lane"])
            out = Path(cfg["paths"]["output"], f"{acc['id']}__{jid}.mp4")
            meta = render_clip(src, clip, acc, hook, out, cfg, seed=jid)
            job = {
                "id": jid, "account_id": acc["id"], "platform": acc["platform"],
                "campaign_id": campaign_id, "source": str(src), "source_label": source_label,
                "highlight": clip, "render": meta, "file": str(out), "hook": hook,
                "caption": caption(acc["lane"], hook, acc.get("hashtags", [])),
                "title": hook[:90] + (" #shorts" if acc["platform"] == "youtube" else ""),
                "status": "pending", "created": dt.datetime.now().isoformat(),
                "checks": {"no_story_spoiler": None, "no_licensed_music": None,
                           "footage_rights_ok": None, "disclosure_ok": None},
            }
            write_json(Path(cfg["paths"]["queue"], "pending", f"{jid}.json"), job)
            jobs.append(job)
            log(cfg, f"[render] {acc['id']} <- {clip['start']}-{clip['end']}s score={clip['score']}")
    return jobs


def list_jobs(cfg, state):
    return sorted(Path(cfg["paths"]["queue"], state).glob("*.json"))


def review(cfg, job_id, approve, hook=None, caption_text=None, checks=None):
    p = Path(cfg["paths"]["queue"], "pending", f"{job_id}.json")
    job = read_json(p)
    if hook:
        job["hook"] = hook
    if caption_text:
        job["caption"] = caption_text
    if checks:
        job["checks"].update(checks)
    if approve:
        lock = dt.date.fromisoformat(cfg["project"]["spoiler_lock_until"])
        if dt.date.today() <= lock and not job["checks"].get("no_story_spoiler"):
            raise ValueError("Spoiler lock active: confirm no_story_spoiler before approving.")
        if not job["checks"].get("footage_rights_ok"):
            raise ValueError("Confirm footage_rights_ok (own capture or permitted stream).")
        camp = next((c for c in cfg["campaigns"] if c["id"] == job["campaign_id"]), {})
        if camp.get("disclosure_required") and not job["checks"].get("disclosure_ok"):
            raise ValueError("Campaign requires an ad disclosure; confirm disclosure_ok.")
    job["status"] = "approved" if approve else "rejected"
    write_json(Path(cfg["paths"]["queue"], job["status"], f"{job_id}.json"), job)
    p.unlink()
    return job


def _slots(window, day, tz):
    a, b = window.split("-")
    s = dt.datetime.combine(day, dt.time.fromisoformat(a), tz)
    e = dt.datetime.combine(day, dt.time.fromisoformat(b), tz)
    return s, e


def schedule(cfg, days=2):
    """Assign approved jobs to jittered slots inside each account's windows."""
    tz = ZoneInfo(cfg["project"]["timezone"])
    now = dt.datetime.now(tz)
    by_acc = {}
    for p in list_jobs(cfg, "approved"):
        j = read_json(p)
        if not j.get("scheduled_for"):
            by_acc.setdefault(j["account_id"], []).append((p, j))
    out = []
    for acc in cfg["accounts"]:
        jobs = by_acc.get(acc["id"], [])
        if not jobs:
            continue
        taken = []
        for p in list_jobs(cfg, "approved"):
            j = read_json(p)
            if j["account_id"] == acc["id"] and j.get("scheduled_for"):
                taken.append(dt.datetime.fromisoformat(j["scheduled_for"]))
        for d in range(days + 1):
            day = (now + dt.timedelta(days=d)).date()
            # vary volume day to day (never the same count every day)
            cap = max(1, acc["daily_max"] - random.choice([0, 0, 1]))
            used = sum(1 for t in taken if t.date() == day)
            for w in random.sample(acc["windows"], len(acc["windows"])):
                if not jobs or used >= cap:
                    break
                s, e = _slots(w, day, tz)
                if e <= now:
                    continue
                s = max(s, now + dt.timedelta(minutes=5))
                t = s + dt.timedelta(seconds=random.uniform(0, (e - s).total_seconds()))
                p, j = jobs.pop(0)
                j["scheduled_for"] = t.isoformat()
                write_json(p, j)
                taken.append(t)
                used += 1
                out.append(j)
    return out


def due_jobs(cfg):
    tz = ZoneInfo(cfg["project"]["timezone"])
    now = dt.datetime.now(tz)
    for p in list_jobs(cfg, "approved"):
        j = read_json(p)
        if j.get("scheduled_for") and dt.datetime.fromisoformat(j["scheduled_for"]) <= now:
            yield p, j


def mark_posted(cfg, path, job, result):
    job["status"] = "posted"
    job.setdefault("posted_at", dt.datetime.now().astimezone().isoformat())
    job["post_result"] = result
    write_json(Path(cfg["paths"]["queue"], "posted", Path(path).name), job)
    Path(path).unlink()


def export_pack(cfg, job, dest):
    """Manual-posting fallback: file + caption ready to AirDrop/upload from a phone."""
    d = Path(dest, job["account_id"])
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(job["file"], d / Path(job["file"]).name)
    (d / (Path(job["file"]).stem + ".txt")).write_text(
        f"{job['caption']}\n\nScheduled: {job.get('scheduled_for','')}\nCampaign: {job['campaign_id']}\n")
    return d
