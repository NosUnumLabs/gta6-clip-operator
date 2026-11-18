# GTA 6 Clip Operator (v2, autonomous)

Clips GTA 6 streamer VODs that a paid campaign names, renders captioned 9:16
Shorts, approves them by itself, posts through Buffer, and learns from results.
Runs free on GitHub Actions every 30 min. Setup: see **SETUP.md**.

```
campaign sources ─► new VODs ─► audio (+Twitch chat) highlight detection ─► download only those sections
     ─► GATES: rights · cutscene (letterbox) · duplicate (dHash) · silent/black · disclosure · quality floor
     ─► captions (faster-whisper) + learner-chosen hook ─► render 1080×1920
     ─► learner ranks candidates ─► approve up to daily capacity ─► Buffer (exact publish time)
     ─► ntfy "SUBMIT NOW" push for campaign clips ─► 48 h later: views ─► learner update
```

## The approval agent ("no slop")
Hard gates reject anything that is not clearly allowed: footage not named by an active
campaign, letterboxed cinematic scenes (story/cutscene → Rockstar takedown risk),
near-duplicates of earlier clips, silent/black/too-short clips, weak highlights, VODs
whose title signals an ending/finale, missing ad disclosure.

Survivors are ranked by a Thompson-sampling learner over hook template, clip length,
streamer and time slot. "Success" = 48 h views above the channel's running median, so
the bar rises as the channel grows. A daily market scan of the top GTA 6 Shorts
(YouTube Data API) nudges length priors and caption keywords toward what's winning.
Only the top clips up to `daily_max` are posted; the rest are dropped.

`python3 run.py brain` shows what it currently believes.

## Commands
```
python3 run.py cycle [--live]     # one full autonomous pass (what the cron runs)
python3 run.py brain              # learner state
python3 run.py report             # posted/rejected counts, est. payout
python3 run.py buffer-setup       # list Buffer channel ids
# manual mode (v1) still works: ingest / pending / approve / schedule / publish / pack
```

## Known limits (honest)
- **Campaign submission is manual.** Content Rewards and Vyro have no submit API; the push
  alert links you straight to the campaign 2–3 min after the post goes live.
- **Source downloads from GitHub's servers:** Twitch VODs generally work; YouTube blocks
  datacenter IPs; Kick can be flaky. If a source fails, run `python3 run.py cycle --live`
  on any home computer instead (same code, residential IP).
- **Cutscene detection is a heuristic** (letterbox bars). Dark night scenes could
  occasionally be rejected; real cutscenes without bars could slip through.
- **In-game licensed radio** can trigger a Content ID claim on a Short (usually revenue
  goes to the label; occasionally blocked). Streamer voice is kept because it is the content.
- Rockstar's policy tolerates non-commercial fan footage; paid clipping is a gray area
  and Take-Two can take any clip down.
- Buffer free plan: 3 channels, 10 queued posts per channel (operator queues ≤8).
