"""Renders one highlight into a vertical 9:16 clip tailored to one account.

Every account gets its own render (own trim, framing, hook, caption look), so no
two posts are the same file — campaign rules reject duplicates and platforms
suppress them.
"""
import random, tempfile
from pathlib import Path
from .util import run, has_audio


def _textfile(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write(text)
    f.close()
    return f.name.replace(":", r"\:")


def _wrap(text, width=22):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def render_clip(src, clip, account, hook, out_path, cfg, seed=None, ass_path=None, jitter=True, disclosure=None,
                facecam=None):
    r = cfg["render"]
    rng = random.Random(seed)
    W, H = r["width"], r["height"]
    font = cfg["paths"]["font"]
    style = account.get("caption_style", {})

    # per-account variation: trim jitter + framing zoom
    j = 1.0 if jitter else 0.0
    start = max(0.0, clip["start"] + j * rng.uniform(-0.6, 0.4))
    end = clip["end"] + j * rng.uniform(-0.4, 0.6)
    dur = max(3.0, end - start)
    zoom = rng.uniform(1.0, 1.12)

    layout = r.get("layout", "blurfill")
    if layout == "auto":
        layout = "facecam_rect" if facecam else "blurfill"
    hook_y = "h*0.16"
    if layout == "facecam_rect":
        fx, fy, fw, fh = facecam
        top = int(H * 0.36) // 2 * 2
        bot = H - top
        v = (f"[0:v]split[a][b];"
             f"[a]crop={fw}:{fh}:{fx}:{fy},scale={W}:{top}:force_original_aspect_ratio=increase,crop={W}:{top}[cam];"
             f"[b]scale=-2:{bot},crop={W}:{bot}[game];"
             f"[cam][game]vstack,setsar=1[base]")
        hook_y = f"{top}-text_h/2"   # hook sits on the seam between face and gameplay
    elif layout == "crop":
        v = (f"[0:v]scale=-2:{int(H*zoom)},crop={W}:{H},setsar=1[base]")
    elif layout == "facecam_stack":
        x, y, w, h = r["facecam_box"]
        v = (f"[0:v]split[a][b];"
             f"[a]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={W}:{int(H*0.35)}:force_original_aspect_ratio=increase,"
             f"crop={W}:{int(H*0.35)}[cam];"
             f"[b]scale=-2:{int(H*0.65)},crop={W}:{int(H*0.65)}[game];"
             f"[cam][game]vstack,setsar=1[base]")
    else:  # blurfill
        fgw = int(W * zoom) // 2 * 2
        v = (f"[0:v]split[a][b];"
             f"[a]scale={W//4}:{H//4}:force_original_aspect_ratio=increase,crop={W//4}:{H//4},"
             f"boxblur=6:2,eq=brightness=-0.08,scale={W}:{H}[bg];"
             f"[b]scale={fgw}:-2,crop='min(iw,{W})':ih[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2-80,setsar=1[base]")

    size = style.get("size", 64)
    color = style.get("color", "white")
    box = style.get("box", "black@0.55")
    hook_tf = _textfile(_wrap(hook.upper() if rng.random() < 0.5 else hook))
    hs = r.get("hook_seconds", 2.5)
    draws = [f"drawtext=fontfile={font}:textfile={hook_tf}:fontsize={size}:fontcolor={color}:"
             f"box=1:boxcolor={box}:boxborderw=24:line_spacing=10:x=(w-text_w)/2:y={hook_y}:"
             f"enable='lt(t,{hs})'"]
    disc = disclosure or r.get("disclosure_text") or account.get("disclosure_text", "")
    if disc:
        draws.append(f"drawtext=fontfile={font}:textfile={_textfile(disc)}:fontsize=40:"
                     f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=40:y=60:enable='lt(t,3)'")
    handle = account.get("handle", "")
    if handle and handle != "@TBD":
        draws.append(f"drawtext=fontfile={font}:textfile={_textfile(handle)}:fontsize=34:"
                     f"fontcolor=white@0.7:x=(w-text_w)/2:y=h*0.86")
    if ass_path:
        draws.insert(0, "ass=" + str(ass_path).replace(":", r"\:"))
    v += ";[base]" + ",".join(draws) + "[v]"

    inputs = ["-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src)]
    mode = r.get("audio_mode", "keep")
    rep = r.get("replacement_audio") or ""
    src_audio = has_audio(src)
    if mode in ("replace", "duck") and rep and Path(rep).exists():
        inputs += ["-stream_loop", "-1", "-i", rep]
        if mode == "duck" and src_audio:
            a = "[0:a]volume=0.3[g];[1:a]volume=0.9[m];[g][m]amix=inputs=2:duration=first[aout]"
        else:
            a = "[1:a]anull[aout]"
    elif mode == "keep" and src_audio:
        a = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    else:
        inputs += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        a = "[1:a]anull[aout]"

    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", v + ";" + a, "-map", "[v]", "-map", "[aout]",
            "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", r.get("preset", "veryfast"),
            "-crf", str(r.get("crf", 21)), "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)])
    run(cmd)
    return {"start": round(start, 2), "duration": round(dur, 2), "zoom": round(zoom, 3)}


def assemble(src, segs, out_path, cold_open=None):
    """Cut `src` down to `segs` (jump cuts over dead air). If `cold_open=(a, b)`, that slice
    (the payoff) plays first as a 1-2 s flash-forward hook, then the clip from its setup."""
    parts = ([cold_open] if cold_open else []) + list(segs)
    fc, n = [], 0
    for i, (a, b) in enumerate(parts):
        fc.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{i}]")
        fc.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.03,afade=t=out:st={max(0.0, b - a - 0.04):.3f}:d=0.04[a{i}]")
        n += 1
    fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", ";".join(fc),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
         "-c:a", "aac", "-b:a", "192k", str(out_path)])
    cold_len = (cold_open[1] - cold_open[0]) if cold_open else 0.0
    return out_path, round(cold_len, 3), round(sum(b - a for a, b in parts), 3)
