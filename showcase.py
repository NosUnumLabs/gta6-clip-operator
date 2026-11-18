#!/usr/bin/env python3
"""In-house engine test on real GTA V stream footage. Nothing is posted.

Finds a recent GTA V VOD on Kick, analyses a 40-minute window, renders the top
highlights through the full production pipeline (detection -> sentence-snapped edit ->
dead-air cuts -> cold open -> verbatim-quote hook -> captions -> compliance checklist),
and writes clips + contact sheets + report to showcase_out/.
"""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.util import load_config, new_id
from engine import autoreview, learner, sources
from engine.detect import find_highlights
from engine import agent

OUT = Path("showcase_out")
CHANNELS = ["dasgasd3m"]   # only the streamer whose campaign we joined
WINDOW_START, WINDOW_LEN = 600, 2400    # 10 min in, analyse 40 min


def find_gta_vod():
    for ch in CHANNELS:
        try:
            r = requests.get(f"https://kick.com/api/v2/channels/{ch}/videos",
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30)
            if r.status_code != 200:
                print(f"[showcase] {ch}: HTTP {r.status_code}")
                continue
            for v in sorted(r.json(), key=lambda v: -(v.get("duration") or 0)):
                cats = " ".join(c.get("name", "") for c in (v.get("categories") or []))
                text = f"{v.get('session_title','')} {cats}".lower()
                src = v.get("source") or (v.get("video") or {}).get("source")
                dur = (v.get("duration") or 0) / 1000
                if src and dur > 1500:
                    print(f"[showcase] using {ch}: '{v.get('session_title')}' ({cats}) {dur/3600:.1f} h")
                    return {"id": f"kick:{ch}", "url": f"https://kick.com/{ch}", "hls": src,
                            "title": v.get("session_title") or "", "streamer": ch, "date": ""}
        except Exception as e:
            print(f"[showcase] {ch}: {e}")
    return None


def ff(args, t=3600):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-user_agent", "Mozilla/5.0"] + args,
                   check=True, timeout=t)


def contact_sheet(mp4, png, times=(0.6, 3.0, 8.0, 15.0)):
    tiles = []
    for i, t in enumerate(times):
        f = Path(tempfile.gettempdir(), f"cs{i}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(mp4), "-frames:v", "1",
                        "-vf", "scale=270:-1", str(f)], check=False)
        if f.exists():
            tiles.append(f)
    if tiles:
        inputs = sum([["-i", str(t)] for t in tiles], [])
        subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex",
                        f"hstack=inputs={len(tiles)}" if len(tiles) > 1 else "null", str(png)], check=False)


def main():
    cfg = load_config()
    OUT.mkdir(exist_ok=True)
    vod = find_gta_vod()
    if not vod:
        print("[showcase] no GTA VOD found on the listed Kick channels")
        (OUT / "report.json").write_text(json.dumps({"error": "no GTA VOD found"}))
        return
    work = Path(tempfile.mkdtemp())
    audio = work / "window.m4a"
    t0 = time.time()
    ff(["-ss", str(WINDOW_START), "-i", vod["hls"], "-t", str(WINDOW_LEN), "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "aac", "-b:a", "48k", str(audio)])
    print(f"[showcase] audio window fetched in {time.time()-t0:.0f}s")
    clips, dur = find_highlights(audio, cfg)
    print(f"[showcase] {len(clips)} highlights in {dur/60:.0f} min")

    camp = dict(next(c for c in cfg["campaigns"] if c["id"] == "ruckus_dasgasd3m"))
    camp.update(id="showcase_test", start_at=None, end_at=None, streamer=vod["streamer"],
                required_hashtags=["#gta"], required_credit=[f"kick.com/{vod['streamer']}"],
                caption_suffix=f"Watch {vod['streamer']} live: kick.com/{vod['streamer']}",
                disclosure_required=False, disclosure_text="")
    acc = next(a for a in cfg["accounts"] if a["id"] == "yt_main")
    L = learner.load()
    report = {"vod": {k: vod[k] for k in ("url", "title", "streamer")}, "window_s": [WINDOW_START, WINDOW_LEN],
              "highlights": len(clips), "clips": []}
    pad = 3.0
    for c in clips[:4]:
        tag = new_id()
        s0 = max(0.0, c["start"] - pad)
        sec = work / f"{tag}.mp4"
        ff(["-ss", f"{WINDOW_START + s0:.2f}", "-i", vod["hls"], "-t", f"{c['end'] - s0 + pad:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", str(sec)], 1800)
        local = {"start": c["start"] - s0, "end": c["end"] - s0, "score": c["score"],
                 "peak": c["peak"], "peak_rel": c["peak"] - s0}
        insp = autoreview.inspect(sec, cfg)
        job = agent._render_job(cfg, L, camp, acc, vod, sec, local, insp, tag)
        fails = autoreview.gates(job, insp, cfg, [], camp) + job.pop("_compliance_fail", [])
        dst = OUT / f"clip_{len(report['clips'])+1}.mp4"
        shutil.move(job["file"], dst)
        contact_sheet(dst, OUT / f"clip_{len(report['clips'])+1}_frames.png")
        report["clips"].append({
            "file": dst.name, "verdict": "APPROVE" if not fails else "REJECT", "reasons": fails,
            "title": job["title"], "hook": job["hook"], "hook_kind": job["hook_kind"],
            "quality": job["quality"], "duration": job["render"]["duration"],
            "vod_time": f"{(WINDOW_START + c['start'])/60:.1f} min", "edit": job["edit"],
            "caption": job["caption"], "caption_words": job["caption_words"],
            "compliance": {k: v["pass"] for k, v in job["compliance"].items()},
            "transcript_excerpt": job["transcript"][:400]})
        print(f"[showcase] clip {dst.name}: {report['clips'][-1]['verdict']} q={job['quality']} '{job['title']}'")
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
