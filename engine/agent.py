"""The autonomous operator. One `cycle()` = one full pass; GitHub Actions runs it on a cron.

  discover new VODs from campaign-named sources
  -> audio-only highlight detection (+ Twitch chat bursts when available)
  -> download just those sections -> compliance gates (rights, cutscene, duplicate, ...)
  -> captions + learner-chosen hook -> render
  -> rank all candidates with the learner, approve only up to daily capacity
  -> schedule -> post via Buffer -> push "submit now" alerts for campaign clips
  -> after 48 h, read views back and update the learner
"""
import datetime as dt, json, os, random, shutil, tempfile, time
from pathlib import Path
from zoneinfo import ZoneInfo
from .util import write_json, read_json, log, new_id
from . import sources, autoreview, learner, pipeline, captions, notify
from .detect import find_highlights
from .render import render_clip
from .hooks import hook_ids, hook_text, caption
from .publish import publish, buffer_post_info


def _campaigns(cfg):
    now = dt.datetime.now().astimezone()
    out = []
    for c in cfg["campaigns"]:
        if not (c.get("active", True) and c.get("sources")):
            continue
        if c.get("start_at") and now < dt.datetime.fromisoformat(c["start_at"]):
            continue
        if c.get("end_at") and now > dt.datetime.fromisoformat(c["end_at"]):
            continue
        out.append(c)
    return out


def _history_hashes(cfg, L):
    hs = list(L.get("hashes", []))
    for state in ("pending", "approved"):
        for p in pipeline.list_jobs(cfg, state):
            hs.append(read_json(p).get("inspect", {}).get("hash", []))
    return hs


def produce(cfg, L, max_vods=2, per_vod=6):
    made = 0
    work = Path(tempfile.mkdtemp(prefix="clipwork_"))
    pad = 3.0
    try:
        for camp in _campaigns(cfg):
            accounts = [a for a in cfg["accounts"] if a["platform"] in camp.get("platforms", [])
                        and a.get("active", True)]
            if not accounts:
                continue
            for vod in sources.new_vods(camp)[:max_vods]:
                try:
                    audio = sources.fetch_audio(vod, work)
                    chat = sources.fetch_chat(vod, work)
                    clips, dur = find_highlights(audio, cfg, chat_offsets=chat)
                    log(cfg, f"[agent] {vod['streamer']} '{vod['title'][:50]}' {dur/60:.0f}min "
                             f"-> {len(clips)} highlights (chat={'yes' if chat else 'no'})")
                    for i, c in enumerate(clips[:per_vod]):
                        tag = new_id()
                        s0 = max(0.0, c["start"] - pad)
                        sec = sources.fetch_section(vod, s0, c["end"] + pad, work, tag)
                        local = {"start": c["start"] - s0, "end": c["end"] - s0,
                                 "score": c["score"], "peak": c["peak"]}
                        insp = autoreview.inspect(sec, cfg)
                        acc = accounts[made % len(accounts)]
                        job = _render_job(cfg, L, camp, acc, vod, sec, local, insp, tag)
                        reasons = autoreview.gates(job, insp, cfg, _history_hashes(cfg, L), camp)
                        if reasons:
                            job["status"] = "rejected"
                            job["reject_reasons"] = reasons
                            write_json(Path(cfg["paths"]["queue"], "rejected", f"{tag}.json"), job)
                            Path(job["file"]).unlink(missing_ok=True)
                            log(cfg, f"[gate] reject {tag}: {'; '.join(reasons)}")
                        else:
                            write_json(Path(cfg["paths"]["queue"], "pending", f"{tag}.json"), job)
                            made += 1
                        sec.unlink(missing_ok=True)
                    sources.mark_processed(vod["id"])
                except Exception as e:
                    log(cfg, f"[agent] VOD failed {vod.get('url')}: {e}")
                finally:
                    for f in work.glob("*"):
                        f.unlink(missing_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return made


def _render_job(cfg, L, camp, acc, vod, sec, clip, insp, tag):
    lane = acc.get("lane", "streamer")
    hid = learner.choose(L, "hook", hook_ids(lane))
    streamer = camp.get("streamer") or vod.get("streamer", "")
    hook = hook_text(lane, hid, streamer)
    ass = None
    words = captions.transcribe(sec) if cfg.get("captions", {}).get("enabled", True) else None
    if words:
        rel = [(s - clip["start"], e - clip["start"], w) for s, e, w in words
               if clip["start"] <= s < clip["end"]]
        if rel:
            ass = Path(cfg["paths"]["output"], f"{tag}.ass")
            captions.write_ass(rel, ass, font=cfg.get("captions", {}).get("font_name", "DejaVu Sans"))
    out = Path(cfg["paths"]["output"], f"{acc['id']}__{tag}.mp4")
    meta = render_clip(sec, clip, acc, hook, out, cfg, seed=tag, ass_path=ass, jitter=False,
                       disclosure=camp.get("disclosure_text") if camp.get("disclosure_required") else None)
    if ass:
        ass.unlink(missing_ok=True)
    cap = caption(lane, hook, acc.get("hashtags", []) + camp.get("required_hashtags", []),
                  streamer=streamer, extra_terms=L.get("trend_terms", [])[:2],
                  suffix=camp.get("caption_suffix", ""))
    return {
        "id": tag, "account_id": acc["id"], "platform": acc["platform"], "campaign_id": camp["id"],
        "campaign_url": camp.get("url", ""), "submit_within_min": camp.get("submit_within_min", 0),
        "after_post_note": camp.get("after_post_note", ""),
        "source": vod["url"], "vod_title": vod.get("title", ""), "streamer": streamer,
        "rights_ok": True,  # only campaign-named sources reach this point
        "highlight": clip, "render": meta, "file": str(out), "hook": hook, "hook_id": hid,
        "captions": bool(ass), "caption": cap,
        "title": (hook[:90] + " #gta6 #shorts") if acc["platform"] == "youtube" else hook,
        "inspect": insp, "status": "pending", "created": dt.datetime.now().isoformat(),
        "checks": {"no_story_spoiler": True, "no_licensed_music": None,
                   "footage_rights_ok": True, "disclosure_ok": True},
    }


def auto_approve(cfg, L):
    """Rank pending clips by learner value; approve up to each account's free capacity."""
    tz = ZoneInfo(cfg["project"]["timezone"])
    today = dt.datetime.now(tz).date()
    used = {}
    for state in ("approved", "posted"):
        for p in pipeline.list_jobs(cfg, state):
            j = read_json(p)
            when = j.get("scheduled_for") or j.get("posted_at") or ""
            if when[:10] >= today.isoformat():
                used[j["account_id"]] = used.get(j["account_id"], 0) + 1
    cands = []
    for p in pipeline.list_jobs(cfg, "pending"):
        j = read_json(p)
        if not Path(j["file"]).exists():
            j["status"] = "rejected"; j["reject_reasons"] = ["render lost between runs"]
            write_json(Path(cfg["paths"]["queue"], "rejected", p.name), j); p.unlink(); continue
        j["value"] = round(learner.expected_value(L, j), 4)
        cands.append((j["value"], p, j))
    cands.sort(key=lambda x: -x[0])
    approved = 0
    stale_h = cfg["autoreview"].get("stale_hours", 18)
    for val, p, j in cands:
        acc = next(a for a in cfg["accounts"] if a["id"] == j["account_id"])
        cap = acc["daily_max"] * (cfg["autoreview"].get("days_ahead", 1) + 1)
        if used.get(acc["id"], 0) < cap and val >= cfg["autoreview"]["min_value"]:
            j["status"] = "approved"
            j["approved_by"] = "autoreview"
            write_json(Path(cfg["paths"]["queue"], "approved", p.name), j)
            p.unlink()
            used[acc["id"]] = used.get(acc["id"], 0) + 1
            approved += 1
        else:
            age_h = (time.time() - dt.datetime.fromisoformat(j["created"]).timestamp()) / 3600
            if age_h > stale_h or val < cfg["autoreview"]["min_value"]:
                j["status"] = "rejected"
                j["reject_reasons"] = [f"ranked out (value {val:.3f})"]
                write_json(Path(cfg["paths"]["queue"], "rejected", p.name), j)
                p.unlink()
                Path(j["file"]).unlink(missing_ok=True)
    return approved


def post_due(cfg, L, live):
    """Hand every scheduled clip to Buffer with its exact publish time, and pre-schedule
    the 'submit now' push for that moment. Cron delays therefore never make a post late."""
    n = 0
    horizon = time.time() + 35 * 60  # hand off only what goes live before the next run
    for p in pipeline.list_jobs(cfg, "approved"):
        job = read_json(p)
        if not job.get("scheduled_for"):
            continue
        if live and not job.get("media_url") and Path(job["file"]).exists():
            try:  # park the render online now; runners are wiped between cycles
                from .publish import host_media
                job["media_url"] = host_media(job["file"])
                write_json(p, job)
            except Exception as e:
                log(cfg, f"[media] hosting failed {job['id']}: {e}")
        if dt.datetime.fromisoformat(job["scheduled_for"]).timestamp() > horizon:
            continue
        if not live and not Path(job["file"]).exists():
            continue
        if live and not Path(job["file"]).exists() and not job.get("media_url"):
            job["status"] = "rejected"; job["reject_reasons"] = ["render lost before hand-off"]
            write_json(Path(cfg["paths"]["queue"], "rejected", p.name), job); p.unlink(); continue
        due = max(time.time() + 120, dt.datetime.fromisoformat(job["scheduled_for"]).timestamp())
        job["due_ts"] = due
        try:
            res = publish(job, cfg, live=live)
            if not live:
                log(cfg, f"[post dry] {job['account_id']} {Path(job['file']).name} at {job['scheduled_for']}")
                continue
            job["posted_at"] = job["scheduled_for"]
            pipeline.mark_posted(cfg, p, job, res)
            learner.remember_hash(L, job.get("inspect", {}).get("hash", []))
            Path(job["file"]).unlink(missing_ok=True)
            n += 1
            acc = next(a for a in cfg["accounts"] if a["id"] == job["account_id"])
            if job.get("campaign_url"):
                chan = acc.get("channel_url") or f"https://www.youtube.com/{acc['handle']}/shorts"
                extra = ("\n3) " + job["after_post_note"]) if job.get("after_post_note") else ""
                notify.push(f"SUBMIT within {job.get('submit_within_min') or 30} min: {job['campaign_id']}",
                            f"New clip going live: \"{job['hook']}\"\n1) Copy its link from your "
                            f"channel: {chan}\n2) Open the campaign -> Submit clip -> paste.{extra}",
                            url=job["campaign_url"], priority="high", tags="moneybag", at=due + 150)
            log(cfg, f"[post LIVE] {job['account_id']} queued in Buffer for {job['scheduled_for']}")
        except Exception as e:
            log(cfg, f"[post ERROR] {job['id']}: {e}")
            notify.push("Post failed", f"{job['id']}: {str(e)[:200]}", priority="low")
    return n


def refresh_links(cfg):
    """Fill in the public post link once Buffer has published (used for stats)."""
    for p in pipeline.list_jobs(cfg, "posted"):
        j = read_json(p)
        bid = (j.get("post_result") or {}).get("buffer_post_id")
        if j.get("post_link") or not bid:
            continue
        if dt.datetime.fromisoformat(j["posted_at"]).timestamp() > time.time():
            continue
        try:
            info = buffer_post_info(bid)
            if info.get("link"):
                j["post_link"] = info["link"]
                write_json(p, j)
        except Exception:
            pass


def learn_from_results(cfg, L):
    """48 h after posting, read views and update the learner (once per clip)."""
    yt_key = os.environ.get("YT_API_KEY")
    updated = 0
    for p in pipeline.list_jobs(cfg, "posted"):
        j = read_json(p)
        if j.get("outcome_recorded") or not j.get("posted_at"):
            continue
        age_h = (time.time() - dt.datetime.fromisoformat(j["posted_at"]).timestamp()) / 3600
        if age_h < 48:
            continue
        views = None
        bid = (j.get("post_result") or {}).get("buffer_post_id")
        if bid:
            try:
                views = buffer_post_info(bid).get("views")
            except Exception:
                pass
        link = j.get("post_link") or ""
        if views is None and "youtu" in link and yt_key:
            vid = link.rstrip("/").split("/")[-1].split("?")[0].replace("watch?v=", "")
            views = learner.youtube_views(yt_key, [vid]).get(vid)
        if views is None:
            if age_h > 96:  # give up, don't let it block learning forever
                j["outcome_recorded"] = "unknown"
                write_json(p, j)
            continue
        j["views"] = int(views)
        j["win"] = learner.record_outcome(L, j, int(views))
        j["outcome_recorded"] = True
        write_json(p, j)
        updated += 1
    return updated


def digest(cfg, L):
    tz = ZoneInfo(cfg["project"]["timezone"])
    now = dt.datetime.now(tz)
    mark = Path(cfg["paths"]["logs"], "last_digest")
    if mark.exists() and mark.read_text() == now.date().isoformat() or now.hour < 8:
        return
    camps = {c["id"]: c for c in cfg["campaigns"]}
    posted = [read_json(p) for p in pipeline.list_jobs(cfg, "posted")]
    views = sum(j.get("views", 0) for j in posted)
    est = 0.0
    for j in posted:
        c = camps.get(j["campaign_id"], {})
        v = j.get("views", 0) / 1000 * c.get("rate_per_1k", 0)
        est += min(v, c["cap_per_clip"]) if c.get("cap_per_clip") else v
    rej = [read_json(p) for p in pipeline.list_jobs(cfg, "rejected")]
    best = sorted(((k[5:], v[0] / sum(v)) for k, v in L["arms"].items() if k.startswith("hook:")),
                  key=lambda x: -x[1])[:2]
    notify.push("Daily clip digest",
                f"Posted total: {len(posted)} | measured views: {views:,}\n"
                f"Est. campaign earnings (pre-fee): ${est*0.9:,.2f}\n"
                f"Rejected by gates: {len(rej)}\nTop hooks: {best}\n"
                f"Trends: {', '.join(L.get('trend_terms', [])[:5])}")
    mark.write_text(now.date().isoformat())


def cycle(cfg, live=False):
    L = learner.load()
    try:
        scan = learner.market_scan(L, os.environ.get("YT_API_KEY"))
        if scan:
            log(cfg, f"[learner] market scan: {scan}")
        made = produce(cfg, L, max_vods=cfg["autoreview"].get("max_vods_per_cycle", 2),
                       per_vod=cfg["autoreview"].get("candidates_per_vod", 6))
        appr = auto_approve(cfg, L)
        sched = pipeline.schedule(cfg, days=cfg["autoreview"].get("days_ahead", 1))
        posted = post_due(cfg, L, live)
        if live:
            refresh_links(cfg)
        learned = learn_from_results(cfg, L)
        log(cfg, f"[cycle] made={made} approved={appr} scheduled={len(sched)} "
                 f"posted={posted} learned={learned}")
        digest(cfg, L)
    finally:
        learner.save(L)
