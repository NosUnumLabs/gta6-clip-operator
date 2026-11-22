"""Word-synced burned-in captions (most Shorts are watched muted).

Uses faster-whisper when it is installed (the GitHub runner installs it); if it
is missing or fails, clips render without captions rather than failing.
"""
from pathlib import Path

_MODEL = None
LAST_PROB = None  # mean word confidence of the last transcription


def _pcm16k(path):
    """Decode audio with ffmpeg to 16 kHz mono float32 (avoids PyAV API breakage)."""
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def transcribe(path, model_size="base"):
    global _MODEL, LAST_PROB
    LAST_PROB = None
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        print(f"[captions] faster-whisper import failed: {e!r}")
        return None
    try:
        if _MODEL is None:
            _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
        segs, _ = _MODEL.transcribe(_pcm16k(path), word_timestamps=True, vad_filter=True)
        words, probs = [], []
        for s in segs:
            for w in (s.words or []):
                words.append((float(w.start), float(w.end), w.word.strip()))
                probs.append(float(getattr(w, "probability", 0.8) or 0.8))
        LAST_PROB = sum(probs) / len(probs) if probs else None
        print(f"[captions] {len(words)} words transcribed from {Path(path).name}")
        return words
    except Exception as e:
        import traceback
        print(f"[captions] transcription failed: {e!r}")
        traceback.print_exc()
        return None


def _ts(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(words, out_path, width=1080, height=1920, font="Poppins", size=78,
              color="&H00FFFFFF", highlight="&H0000E5FF", per_line=3, y_frac=0.70):
    """Groups words 3 at a time; the spoken word is highlighted (karaoke style)."""
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{color},{color},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,{int(height*(1-y_frac))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), per_line):
        grp = words[i:i + per_line]
        for j, (ws, we, _) in enumerate(grp):
            end = grp[j + 1][0] if j + 1 < len(grp) else we
            from .edit import mask
            txt = " ".join((r"{\c" + highlight + "}" + mask(w).upper() + r"{\c" + color + "}") if k == j
                           else mask(w).upper() for k, (_, _, w) in enumerate(grp))
            lines.append(f"Dialogue: 0,{_ts(ws)},{_ts(max(end, ws + 0.05))},Cap,,0,0,0,,{txt}")
    Path(out_path).write_text(hdr + "\n".join(lines) + "\n")
    return out_path
