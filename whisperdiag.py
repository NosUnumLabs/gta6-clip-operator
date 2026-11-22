"""Diagnose transcription on the cloud runner; writes diag/diag.txt (uploaded to a private draft release)."""
import subprocess, sys, traceback, os, io, contextlib
from pathlib import Path
out = Path("diag"); out.mkdir(exist_ok=True)
log = open(out / "diag_py.txt", "w")
def p(*a):
    print(*a); print(*a, file=log); log.flush()
try:
    import faster_whisper, ctranslate2, av
    p("versions", faster_whisper.__version__, ctranslate2.__version__, av.__version__)
except Exception:
    p("IMPORT FAIL", traceback.format_exc())
def main():
    try:
        from faster_whisper import WhisperModel
        WhisperModel('base', device='cpu', compute_type='int8'); p('model load OK')
    except Exception:
        p('MODEL LOAD FAIL', traceback.format_exc())
    sys.path.insert(0, ".")
    from engine import sources
    vods = sources._kick_vods("dasgasd3m", 10)
    v = max(vods, key=lambda x: x.get("duration") or 0)
    p("vod", v.get("title"), v.get("duration"))
    wav = out / "s.mp4"
    try:
        sec = sources.fetch_section(v, 1200, 1260, out, "diag")
        p("section", sec, os.path.getsize(sec))
    except Exception:
        p("FETCH FAIL", traceback.format_exc()); sec = None
    if sec:
        subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "compact", str(sec)])
        from faster_whisper import WhisperModel
        for vad in (True, False):
            try:
                m = WhisperModel("base", device="cpu", compute_type="int8")
                segs, info = m.transcribe(str(sec), word_timestamps=True, vad_filter=vad)
                segs = list(segs)
                n = sum(len(s.words or []) for s in segs)
                p(f"vad={vad} lang={info.language} segs={len(segs)} words={n}")
                p("text:", " ".join(s.text for s in segs)[:400])
            except Exception:
                p(f"vad={vad} TRANSCRIBE FAIL", traceback.format_exc())
        try:
            from engine import captions
            w = captions.transcribe(sec)
            p("engine.captions.transcribe ->", None if w is None else len(w))
        except Exception:
            p("ENGINE FAIL", traceback.format_exc())
try:
    main()
except BaseException:
    p('MAIN FAIL', traceback.format_exc())
