"""Footage sourcing: only streams a campaign brief (or written permission) names.

Flow per source channel:
  1. list recent VODs (yt-dlp --flat-playlist)       -> skip ones already processed
  2. download AUDIO ONLY (small, fast)                -> run highlight detection on it
  3. download only the highlight SECTIONS as video    -> render those
This keeps a 6-hour VOD to a few hundred MB instead of many GB.

Local folders/files are accepted as sources too (useful for testing or for
VOD files a campaign shares in a Drive folder that you sync).
"""
import json, re, shutil, subprocess
from pathlib import Path
from .util import log, ROOT

STATE = ROOT / "state" / "sources.json"


def _state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"processed": []}


def _save(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def _ytdlp():
    exe = shutil.which("yt-dlp")
    if not exe:
        raise RuntimeError("yt-dlp not installed (pip install -U 'yt-dlp[default]')")
    return exe


def list_vods(url, limit=5):
    """Return [{id, url, title, duration}] newest first. Local paths are listed directly."""
    p = Path(url)
    if p.exists():
        files = [p] if p.is_file() else sorted(p.glob("*.mp4")) + sorted(p.glob("*.mkv"))
        return [{"id": f"local:{f.resolve()}", "url": str(f), "title": f.stem, "duration": None}
                for f in files]
    r = subprocess.run([_ytdlp(), "--flat-playlist", "--playlist-end", str(limit), "-J", url],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    data = json.loads(r.stdout)
    entries = data.get("entries") or [data]
    out = []
    for e in entries:
        if not e:
            continue
        out.append({"id": f"{e.get('ie_key') or e.get('extractor_key','')}:{e.get('id')}",
                    "url": e.get("url") or e.get("webpage_url"),
                    "title": e.get("title") or "", "duration": e.get("duration")})
    return out


def new_vods(campaign, limit=3):
    s = _state()
    found = []
    for src in campaign.get("sources", []):
        try:
            for v in list_vods(src["url"], limit=limit):
                if v["id"] in s["processed"]:
                    continue
                v["streamer"] = src.get("name", "")
                v["campaign_id"] = campaign["id"]
                found.append(v)
        except Exception as e:
            print(f"[sources] cannot list {src['url']}: {e}")
    return found


def mark_processed(vod_id):
    s = _state()
    if vod_id not in s["processed"]:
        s["processed"].append(vod_id)
        s["processed"] = s["processed"][-500:]
    _save(s)


def fetch_audio(vod, workdir):
    """Audio-only copy for detection. Local files are used as-is."""
    if Path(vod["url"]).exists():
        return Path(vod["url"])
    out = Path(workdir) / (re.sub(r"[^A-Za-z0-9_-]", "_", vod["id"])[:60] + ".m4a")
    subprocess.run([_ytdlp(), "-f", "ba[ext=m4a]/ba/b", "-o", str(out), "--no-part",
                    "--retries", "5", vod["url"]], check=True, timeout=3600,
                   capture_output=True)
    if not out.exists():  # some extractors pick another extension
        cands = list(Path(workdir).glob(out.stem + ".*"))
        if not cands:
            raise RuntimeError("audio download produced no file")
        out = cands[0]
    return out


def fetch_section(vod, start, end, workdir, tag):
    """Video for one highlight window. Local files are cut with ffmpeg."""
    out = Path(workdir) / f"{tag}.mp4"
    if Path(vod["url"]).exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                        "-i", vod["url"], "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                        "-c:a", "aac", str(out)], check=True)
        return out
    subprocess.run([_ytdlp(), "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                    "--download-sections", f"*{start:.1f}-{end:.1f}", "--force-keyframes-at-cuts",
                    "--merge-output-format", "mp4", "-o", str(out), "--no-part", vod["url"]],
                   check=True, timeout=1800, capture_output=True)
    return out


def _offsets(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("content_offset_seconds", "contentOffsetSeconds") and isinstance(v, (int, float)):
                out.append(float(v))
            else:
                _offsets(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _offsets(v, out)


def fetch_chat(vod, workdir):
    """Twitch chat replay timestamps (strongest highlight signal). None if unavailable."""
    if "twitch.tv" not in (vod.get("url") or ""):
        return None
    try:
        base = Path(workdir) / "chat"
        subprocess.run([_ytdlp(), "--skip-download", "--write-subs", "--sub-langs", "rechat",
                        "-o", str(base), vod["url"]], timeout=900, capture_output=True)
        files = list(Path(workdir).glob("chat*.json"))
        if not files:
            return None
        offs = []
        _offsets(json.loads(files[0].read_text()), offs)
        return offs or None
    except Exception:
        return None
