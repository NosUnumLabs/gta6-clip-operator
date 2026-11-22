"""Facecam detection for the stacked streamer-clip layout (benchmark: top-performing
GTA streamer Shorts put the streamer's face big on top and tall gameplay below).

detect_facecam(path) -> (x, y, w, h) crop rect in source pixels around the streamer's
face, or None when no stable face is found (then the renderer falls back to blurfill).
"""
import subprocess
import numpy as np

TOP_FRAC = 0.50          # 50/50 face-over-game, matching top streamer clips (Nov 2026 study); share of the 1080x1920 canvas used by the facecam panel
SAMPLE_W = 640


def _cascade():
    try:
        import cv2
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        c = cv2.CascadeClassifier(path)
        return None if c.empty() else c
    except Exception:
        return None


def _probe_wh(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def detect_facecam(path, n=14):
    casc = _cascade()
    if casc is None:
        return None
    import cv2
    W, H = _probe_wh(path)
    sh = int(SAMPLE_W * H / W) // 2 * 2
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                        f"fps=1,scale={SAMPLE_W}:{sh},format=gray", "-frames:v", str(n),
                        "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.uint8)
    k = len(a) // (SAMPLE_W * sh)
    if k == 0:
        return None
    frames = a[: k * SAMPLE_W * sh].reshape(k, sh, SAMPLE_W)
    boxes = []
    for f in frames:
        faces = casc.detectMultiScale(f, scaleFactor=1.1, minNeighbors=6, minSize=(28, 28))
        if len(faces):
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])  # largest face = streamer
            boxes.append((x + w / 2, y + h / 2, w))
    if len(boxes) < max(3, int(0.4 * k)):
        return None                                   # not on screen consistently
    b = np.array(boxes)
    cx, cy, fw = np.median(b[:, 0]), np.median(b[:, 1]), np.median(b[:, 2])
    if np.std(b[:, 0]) > 0.08 * SAMPLE_W or np.std(b[:, 1]) > 0.08 * sh:
        return None                                   # face wanders: likely in-game, not a cam
    scale = W / SAMPLE_W
    cx, cy, fw = cx * scale, cy * scale, fw * scale
    # panel aspect matches the canvas slot (1080 x 0.36*1920 ≈ 1.56:1); frame the head + shoulders
    aspect = 1080 / (1920 * TOP_FRAC)
    cw = min(W, fw * 3.2)
    ch = min(H, cw / aspect)
    cw = ch * aspect
    x0 = int(np.clip(cx - cw / 2, 0, W - cw))
    y0 = int(np.clip(cy - ch * 0.45, 0, H - ch))
    return (x0, y0, int(cw) // 2 * 2, int(ch) // 2 * 2)
