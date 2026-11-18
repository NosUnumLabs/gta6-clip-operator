#!/usr/bin/env python3
"""GTA 6 Clip Engine CLI.

  python3 run.py ingest input/session1.mp4 [--campaign own_channel] [--lanes chaos,discovery]
  python3 run.py pending                       # list clips waiting for review
  python3 run.py approve <id> --checks all [--hook "..."]   # or: reject <id>
  python3 run.py schedule [--days 2]
  python3 run.py publish [--live]              # posts everything that's due
  python3 run.py pack <dest_dir>               # manual-posting packs for phone upload
  python3 run.py watch [--live] [--interval 120]   # autonomous loop
  python3 run.py report                        # earnings / output summary -> logs/report.csv
  python3 run.py cycle [--live]                # AUTONOMOUS: one full operator pass (cron runs this)
  python3 run.py buffer-setup                  # print Buffer org/channel ids
  python3 run.py brain                         # show what the learner currently believes
"""
import argparse, csv, json, time
from pathlib import Path
from engine.util import load_config, read_json, write_json, log
from engine import pipeline
from engine.publish import publish

ALL_CHECKS = {"no_story_spoiler": True, "no_licensed_music": True,
              "footage_rights_ok": True, "disclosure_ok": True}


def cmd_publish(cfg, live):
    n = 0
    for p, job in pipeline.due_jobs(cfg):
        try:
            res = publish(job, cfg, live=live)
            if live:
                pipeline.mark_posted(cfg, p, job, res)
            log(cfg, f"[publish{'': <1}{'LIVE' if live else 'dry'}] {job['account_id']} {Path(job['file']).name} -> {res}")
            n += 1
        except Exception as e:  # keep the loop alive; one failure shouldn't stop others
            log(cfg, f"[publish ERROR] {job['id']}: {e}")
    return n


def cmd_watch(cfg, live, interval):
    seen_file = Path(cfg["paths"]["logs"], "ingested.json")
    seen = set(json.loads(seen_file.read_text())) if seen_file.exists() else set()
    log(cfg, f"[watch] polling {cfg['paths']['input']} every {interval}s (live={live})")
    while True:
        for f in sorted(Path(cfg["paths"]["input"]).iterdir()):
            if f.suffix.lower() not in pipeline.VIDEO_EXT or str(f) in seen:
                continue
            s1 = f.stat().st_size
            time.sleep(3)
            if f.stat().st_size != s1:  # still being written by the capture app
                continue
            try:
                pipeline.ingest(f, cfg)
            except Exception as e:
                log(cfg, f"[ingest ERROR] {f.name}: {e}")
            seen.add(str(f))
            seen_file.write_text(json.dumps(sorted(seen)))
        if not cfg["project"]["require_human_review"]:
            log(cfg, "[watch] WARNING require_human_review=false — auto-approving is not recommended")
        pipeline.schedule(cfg)
        cmd_publish(cfg, live)
        time.sleep(interval)


def cmd_report(cfg):
    camps = {c["id"]: c for c in cfg["campaigns"]}
    rows = []
    for state in ("pending", "approved", "rejected", "posted"):
        for p in pipeline.list_jobs(cfg, state):
            j = read_json(p)
            c = camps.get(j["campaign_id"], {})
            views = j.get("views", 0)
            gross = views / 1000 * c.get("rate_per_1k", 0)
            if c.get("cap_per_clip"):
                gross = min(gross, c["cap_per_clip"])
            rows.append({"id": j["id"], "state": state, "account": j["account_id"],
                         "campaign": j["campaign_id"], "hook": j["hook"],
                         "scheduled_for": j.get("scheduled_for", ""), "views": views,
                         "est_payout": round(gross * 0.9, 2)})
    out = Path(cfg["paths"]["logs"], "report.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["state"]] = by.get(r["state"], 0) + 1
    print(f"{by}  est. payout ${sum(r['est_payout'] for r in rows):.2f}  -> {out}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("ingest"); a.add_argument("src"); a.add_argument("--campaign", default="own_channel")
    a.add_argument("--lanes"); a.add_argument("--label", default="own_capture")
    sp.add_parser("pending")
    a = sp.add_parser("approve"); a.add_argument("id"); a.add_argument("--checks", default="")
    a.add_argument("--hook"); a.add_argument("--caption")
    a = sp.add_parser("reject"); a.add_argument("id")
    a = sp.add_parser("schedule"); a.add_argument("--days", type=int, default=2)
    a = sp.add_parser("publish"); a.add_argument("--live", action="store_true")
    a = sp.add_parser("pack"); a.add_argument("dest")
    a = sp.add_parser("watch"); a.add_argument("--live", action="store_true")
    a.add_argument("--interval", type=int, default=120)
    a = sp.add_parser("views"); a.add_argument("id"); a.add_argument("views", type=int)
    sp.add_parser("report")
    a = sp.add_parser("cycle"); a.add_argument("--live", action="store_true")
    sp.add_parser("buffer-setup")
    sp.add_parser("brain")
    sp.add_parser("doctor")
    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "ingest":
        jobs = pipeline.ingest(args.src, cfg, args.label, args.campaign,
                               args.lanes.split(",") if args.lanes else None)
        print(f"{len(jobs)} clips rendered -> queue/pending")
    elif args.cmd == "pending":
        for p in pipeline.list_jobs(cfg, "pending"):
            j = read_json(p)
            print(f"{j['id']}  {j['account_id']:<14} score={j['highlight']['score']:<6} "
                  f"{j['render']['duration']:>5}s  hook='{j['hook']}'  file={j['file']}")
    elif args.cmd == "approve":
        checks = ALL_CHECKS if args.checks == "all" else {
            k: True for k in args.checks.split(",") if k}
        j = pipeline.review(cfg, args.id, True, args.hook, args.caption, checks)
        print("approved", j["id"])
    elif args.cmd == "reject":
        pipeline.review(cfg, args.id, False); print("rejected", args.id)
    elif args.cmd == "schedule":
        for j in pipeline.schedule(cfg, args.days):
            print(f"{j['scheduled_for']}  {j['account_id']}  {Path(j['file']).name}")
    elif args.cmd == "publish":
        print(cmd_publish(cfg, args.live), "jobs processed")
    elif args.cmd == "pack":
        for p in pipeline.list_jobs(cfg, "approved"):
            print(pipeline.export_pack(cfg, read_json(p), args.dest))
    elif args.cmd == "watch":
        cmd_watch(cfg, args.live, args.interval)
    elif args.cmd == "views":
        p = Path(cfg["paths"]["queue"], "posted", f"{args.id}.json")
        j = read_json(p); j["views"] = args.views; write_json(p, j); print("updated")
    elif args.cmd == "report":
        cmd_report(cfg)
    elif args.cmd == "cycle":
        from engine.agent import cycle
        cycle(cfg, live=args.live)
    elif args.cmd == "buffer-setup":
        from engine.publish import buffer_setup
        print(json.dumps(buffer_setup(), indent=2))
    elif args.cmd == "doctor":
        import os
        from engine.publish import buffer_setup
        from engine import learner
        ok = True
        try:
            orgs = buffer_setup()
            for o in orgs:
                for c in o["channels"]:
                    print(f"BUFFER OK  channel {c['service']:<10} {c['name']:<28} id={c['id']}")
        except Exception as e:
            ok = False; print("BUFFER FAIL", str(e)[:300])
        try:
            L = learner.load(); L["last_scan"] = 0
            r = learner.market_scan(L, os.environ.get("YT_API_KEY"))
            print("YOUTUBE API OK  top GTA 6 shorts scanned:", r)
            learner.save(L)
        except Exception as e:
            ok = False; print("YOUTUBE API FAIL", str(e)[:300])
        from engine import sources
        for c in cfg["campaigns"]:
            if not c.get("active", True):
                continue
            for src in c.get("sources", []):
                try:
                    vs = sources.list_vods(src["url"], limit=3)
                    print(f"SOURCE OK   {c['id']:<22} {src['url']} -> {len(vs)} items; newest: "
                          f"{(vs[0]['title'][:50] + ' ' + vs[0].get('date','')) if vs else '-'}")
                    if vs:
                        import tempfile, pathlib
                        wd = tempfile.mkdtemp()
                        try:
                            f = sources.fetch_section(vs[0], 60, 70, wd, "dltest")
                            print(f"DOWNLOAD OK {c['id']:<22} 10s section, {pathlib.Path(f).stat().st_size//1024} KB")
                        except Exception as e:
                            err = getattr(e, "stderr", b"") or b""
                            err = err.decode(errors="ignore") if isinstance(err, bytes) else str(err)
                            print(f"DOWNLOAD FAIL {c['id']:<22} {(err or str(e))[-300:]}")
                except Exception as e:
                    print(f"SOURCE FAIL {c['id']:<22} {src['url']}: {str(e)[:200]}")
        for k in ("BUFFER_API_KEY", "YT_API_KEY", "YT_MAIN_BUFFER_CHANNEL_ID", "TT_MAIN_BUFFER_CHANNEL_ID"):
            print(f"{k:<28} {'set' if os.environ.get(k) else 'MISSING'}")
        raise SystemExit(0 if ok else 1)
    elif args.cmd == "brain":
        from engine import learner
        L = learner.load()
        rows = sorted(((k, a / (a + b), a + b - 2) for k, (a, b) in L["arms"].items()),
                      key=lambda x: (x[0].split(":")[0], -x[1]))
        for k, p, n in rows:
            print(f"{k:<28} win-rate {p:5.2f}  (n={n:.0f})")
        print("trend terms:", L.get("trend_terms"))


if __name__ == "__main__":
    main()
