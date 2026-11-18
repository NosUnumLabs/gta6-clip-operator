"""Highlight detection: finds the moments worth clipping in a long capture/VOD.

Signals (cheap, no ML, runs on any machine):
  * audio energy spikes  -> crashes, explosions, gunfire, streamer reactions
  * visual motion/cut density -> chases, wrecks, camera whips, ragdolls
Scores are z-normalised, blended, peak-picked with a minimum gap.
"""
import subprocess
import numpy as np
from .util import probe_duration, has_audio

WIN = 0.5  # seconds per analysis bin


def _audio_curve(path, dur):
    n = int(dur / WIN) + 1
    if not has_audio(path):
        return np.zeros(n)
    sr = 8000
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", str(sr), "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
    hop = int(sr * WIN)
    m = len(x) // hop
    if m == 0:
        return np.zeros(n)
    rms = np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(axis=1) + 1e-9)
    db = 20 * np.log10(rms)
    out = np.full(n, db.min())
    out[: min(n, m)] = db[:n]
    return out


def _motion_curve(path, dur):
    fps, w, h = 1 / WIN * 2, 96, 54  # 4 fps tiny grayscale frames
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                        f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    frames = np.frombuffer(p.stdout, dtype=np.uint8)
    k = len(frames) // (w * h)
    n = int(dur / WIN) + 1
    if k < 2:
        return np.zeros(n)
    f = frames[: k * w * h].reshape(k, h, w).astype(np.float32)
    diff = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    diff = np.concatenate([[0], diff])
    per_bin = int(round(fps * WIN))
    b = len(diff) // per_bin
    curve = diff[: b * per_bin].reshape(b, per_bin).max(axis=1)
    out = np.zeros(n)
    out[: min(n, b)] = curve[:n]
    return out


def _z(a):
    s = a.std()
    return (a - a.mean()) / s if s > 1e-6 else np.zeros_like(a)


def chat_curve(offsets, dur, lag_s=25.0):
    """Chat-message density per bin, shifted back ~25 s (chat reacts after the moment)."""
    n = int(dur / WIN) + 1
    c = np.zeros(n)
    for t in offsets:
        i = int((t - lag_s) / WIN)
        if 0 <= i < n:
            c[i] += 1
    k = np.ones(int(10 / WIN)) / int(10 / WIN)  # 10 s window
    return np.convolve(c, k, mode="same")


def find_highlights(path, cfg, chat_offsets=None):
    d = cfg["detection"]
    dur = probe_duration(path)
    a = _z(_audio_curve(path, dur))
    m = _z(_motion_curve(path, dur))
    n = min(len(a), len(m))
    score = d["loudness_weight"] * a[:n] + d["scene_weight"] * m[:n]
    if chat_offsets is not None and len(chat_offsets) > 50:
        c = _z(chat_curve(chat_offsets, dur))[:n]
        score = score + d.get("chat_weight", 0.8) * c
        # moments where a voice spike and a chat burst coincide are the strongest
        score = score + 0.5 * np.minimum(a[:n], c)
    # smooth (1.5 s) so a sustained chase outranks a single blip
    k = np.ones(3) / 3
    score = np.convolve(score, k, mode="same")

    order = np.argsort(score)[::-1]
    picks, gap = [], d["min_gap_s"] / WIN
    for i in order:
        if score[i] <= 0.5:
            break
        if all(abs(i - j) >= gap for j in picks):
            picks.append(i)
        if len(picks) >= d["top_n_per_source"]:
            break

    clips = []
    for i in picks:
        t = i * WIN
        start = max(0.0, t - d["pre_roll_s"])
        end = min(dur, t + d["post_roll_s"])
        if end - start < d["min_clip_s"]:
            pad = d["min_clip_s"] - (end - start)
            start = max(0.0, start - pad / 2)
            end = min(dur, end + pad / 2)
        end = min(end, start + d["max_clip_s"])
        clips.append({"peak": round(t, 2), "start": round(start, 2),
                      "end": round(end, 2), "score": round(float(score[i]), 3)})
    return sorted(clips, key=lambda c: -c["score"]), dur
