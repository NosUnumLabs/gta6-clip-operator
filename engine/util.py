import json, os, subprocess, time, uuid, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    with open(path or os.environ.get("CLIP_CONFIG") or ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    if not os.path.exists(cfg["paths"].get("font", "")):
        for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
                  "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"):
            if os.path.exists(f):
                cfg["paths"]["font"] = f
                break
    for k, v in cfg["paths"].items():
        if k != "font" and not os.path.isabs(v):
            cfg["paths"][k] = str(ROOT / v)
    for sub in ("pending", "approved", "rejected", "posted"):
        Path(cfg["paths"]["queue"], sub).mkdir(parents=True, exist_ok=True)
    for k in ("input", "output", "logs"):
        Path(cfg["paths"][k]).mkdir(parents=True, exist_ok=True)
    return cfg


def run(cmd, capture=True):
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(path)])
    return bool(r.stdout.strip())


def new_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def log(cfg, msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line)
    with open(Path(cfg["paths"]["logs"], "engine.log"), "a") as f:
        f.write(line + "\n")
