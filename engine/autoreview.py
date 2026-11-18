"""Autonomous approval agent: hard compliance gates first, then learned ranking.

Hard gates (any failure = reject, reason logged):
  rights      the source is named by an active campaign brief (or your permission list)
  cutscene    letterbox bars on most frames = cinematic/story scene (spoiler/takedown risk)
  duplicate   perceptual hash too close to anything already posted or approved
  technical   duration in range, not silent, not mostly black
  disclosure  campaign requires an on-screen ad disclosure and none is configured
  quality     highlight score above the floor (no filler clips)

Ranking: the learner's Thompson sample for (hook, duration bucket, streamer, slot)
combined with the detection strength. Only the top clips up to each account's
daily capacity are approved; the rest are held back, not posted.
"""
import subprocess
import numpy as np
from .util import probe_duration, has_audio

W, H = 64, 36


def _frames(path, fps=2):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                        f"fps={fps},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.uint8)
    k = len(a) // (W * H)
    return a[: k * W * H].reshape(k, H, W).astype(np.float32)


def letterbox_ratio(frames):
    """Share of frames with dark, flat bands top and bottom while the middle has content."""
    if len(frames) == 0:
        return 0.0
    band = max(2, int(H * 0.07))
    top, bot = frames[:, :band, :], frames[:, -band:, :]
    mid = frames[:, band * 2:-band * 2, :]
    # video "black" sits near 16 (TV range) with scaling bleed, so test the 90th percentile
    dark = (np.percentile(top, 90, axis=(1, 2)) < 32) & (np.percentile(bot, 90, axis=(1, 2)) < 32)
    flat = np.ones(len(frames), dtype=bool)
    content = mid.mean(axis=(1, 2)) > 30
    return float((dark & flat & content).mean())


def dhash(frames, n=12):
    """Sequence of 64-bit difference hashes over n evenly spaced frames (centre crop)."""
    if len(frames) == 0:
        return []
    frames = frames[:, int(H * 0.15):int(H * 0.85), int(W * 0.2):int(W * 0.8)]
    idx = np.linspace(0, len(frames) - 1, n).astype(int)
    out = []
    for i in idx:
        f = frames[i]
        h, w = f.shape
        small = np.array([[f[int(r * h / 8):int((r + 1) * h / 8), int(c * w / 9):int((c + 1) * w / 9)].mean()
                           for c in range(9)] for r in range(8)])
        bits = (small[:, 1:] > small[:, :-1]).flatten()
        out.append(int("".join("1" if x else "0" for x in bits), 2))
    return out


def hash_distance(a, b):
    if not a or not b:
        return 64
    n = min(len(a), len(b))
    return float(np.mean([bin(a[i] ^ b[i]).count("1") for i in range(n)]))


def _mean_volume(path):
    if not has_audio(path):
        return -91.0
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split(":")[1].replace("dB", "").strip())
    return -91.0


def inspect(section_path, cfg):
    """Content checks on the raw source section (before branding is drawn on)."""
    fr = _frames(section_path)
    return {
        "letterbox": round(letterbox_ratio(fr), 3),
        "black": round(float((fr.mean(axis=(1, 2)) < 12).mean()) if len(fr) else 1.0, 3),
        "hash": dhash(fr),
        "mean_db": _mean_volume(section_path),
        "duration": probe_duration(section_path),
    }


def gates(job, insp, cfg, history_hashes, campaign):
    ar = cfg["autoreview"]
    reasons = []
    if not job.get("rights_ok"):
        reasons.append("rights: source not named by an active campaign or permission list")
    if insp["letterbox"] >= ar["max_letterbox_ratio"]:
        reasons.append(f"cutscene: letterbox on {insp['letterbox']:.0%} of frames")
    if insp["black"] > 0.35:
        reasons.append("technical: mostly black frames")
    if insp["mean_db"] < -50:
        reasons.append("technical: near-silent audio")
    d = cfg["detection"]
    if not (d["min_clip_s"] - 2 <= insp["duration"] <= d["max_clip_s"] + 6):
        reasons.append(f"technical: duration {insp['duration']:.1f}s out of range")
    if job["highlight"]["score"] < ar["min_highlight_score"]:
        reasons.append(f"quality: highlight score {job['highlight']['score']} < floor")
    near = min((hash_distance(insp["hash"], h) for h in history_hashes), default=64)
    if near < ar["max_dup_distance"]:
        reasons.append(f"duplicate: {near:.1f}-bit distance to an earlier clip")
    if campaign and campaign.get("disclosure_required") and not (
            campaign.get("disclosure_text") or cfg["render"].get("disclosure_text")):
        reasons.append("disclosure: campaign requires an ad disclosure text")
    for kw in campaign.get("title_blocklist", []) if campaign else []:
        if kw.lower() in (job.get("vod_title") or "").lower():
            reasons.append(f"spoiler: VOD title contains '{kw}'")
    return reasons
