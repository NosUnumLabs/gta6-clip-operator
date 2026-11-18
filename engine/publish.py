"""Posting adapters. All default to dry-run; nothing goes live without --live.

Platform realities (Nov 2026):
  * TikTok Content Posting API: unaudited apps can only post SELF_ONLY (private),
    max 5 users/24h. Audit takes days to ~2 weeks. Until audited, use mode
    "draft" (Upload -> lands in the TikTok inbox; you tap Post in the app) or an
    already-audited scheduler (e.g. Blotato/PostPeer/Ayrshare) via its API.
  * YouTube Data API: default 10,000 quota units/day, an upload costs ~1,600
    -> about 6 uploads/day per Google Cloud project.
  * Instagram Graph API: Business/Creator account linked to a Facebook Page;
    the video must be at a public HTTPS URL (set PUBLIC_MEDIA_BASE_URL).
Credentials are read from .env (see .env.example).
"""
import math, os, time
from pathlib import Path
import requests
from .util import ROOT


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _env(acc_id, key):
    return os.environ.get(f"{acc_id.upper()}_{key}") or os.environ.get(key)


# ---------- YouTube ----------
def youtube_upload(job, acc):
    tok = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": _env(acc["id"], "YT_CLIENT_ID"),
        "client_secret": _env(acc["id"], "YT_CLIENT_SECRET"),
        "refresh_token": _env(acc["id"], "YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}, timeout=30).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    body = {"snippet": {"title": job["title"][:100], "description": job["caption"],
                        "categoryId": "20"},  # Gaming
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    size = Path(job["file"]).stat().st_size
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={**h, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        json=body, timeout=30)
    init.raise_for_status()
    with open(job["file"], "rb") as f:
        r = requests.put(init.headers["Location"], headers={**h, "Content-Type": "video/mp4"},
                         data=f, timeout=600)
    r.raise_for_status()
    vid = r.json()["id"]
    return {"platform_id": vid, "url": f"https://youtube.com/shorts/{vid}"}


# ---------- TikTok ----------
def tiktok_upload(job, acc, mode="draft"):
    tok = _env(acc["id"], "TT_ACCESS_TOKEN")
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}
    size = Path(job["file"]).stat().st_size
    chunk = min(size, 10_000_000)
    n = max(1, math.floor(size / chunk))
    src = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": n}
    if mode == "direct":
        url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
        payload = {"post_info": {"title": job["caption"][:2200], "privacy_level":
                                 os.environ.get("TT_PRIVACY", "PUBLIC_TO_EVERYONE"),
                                 "disable_comment": False, "brand_content_toggle":
                                 bool(job.get("paid_partnership"))}, "source_info": src}
    else:
        url = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
        payload = {"source_info": src}
    r = requests.post(url, headers=h, json=payload, timeout=30).json()
    if r.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init error: {r['error']}")
    up, pid = r["data"]["upload_url"], r["data"]["publish_id"]
    with open(job["file"], "rb") as f:
        for i in range(n):
            beg = i * chunk
            data = f.read(chunk if i < n - 1 else size - beg)
            end = beg + len(data) - 1
            requests.put(up, headers={"Content-Type": "video/mp4",
                                      "Content-Range": f"bytes {beg}-{end}/{size}"},
                         data=data, timeout=600).raise_for_status()
    return {"platform_id": pid, "mode": mode,
            "note": "draft in TikTok inbox — open app to post" if mode == "draft" else ""}


# ---------- Instagram ----------
def instagram_upload(job, acc):
    base = os.environ["PUBLIC_MEDIA_BASE_URL"].rstrip("/")
    uid, tok = _env(acc["id"], "IG_USER_ID"), _env(acc["id"], "IG_ACCESS_TOKEN")
    g = "https://graph.facebook.com/v21.0"
    c = requests.post(f"{g}/{uid}/media", data={
        "media_type": "REELS", "video_url": f"{base}/{Path(job['file']).name}",
        "caption": job["caption"], "access_token": tok}, timeout=30).json()
    cid = c["id"]
    for _ in range(60):
        s = requests.get(f"{g}/{cid}", params={"fields": "status_code", "access_token": tok},
                         timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
        time.sleep(10)
    p = requests.post(f"{g}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok},
                      timeout=30).json()
    return {"platform_id": p.get("id")}


def publish(job, cfg, live=False):
    acc = next(a for a in cfg["accounts"] if a["id"] == job["account_id"])
    if not live:
        return {"dry_run": True, "would_post": job["file"], "to": f"{acc['platform']}:{acc['handle']}"}
    load_env()
    if acc.get("via", "buffer") == "buffer":
        return buffer_post(job, acc)
    if acc["platform"] == "youtube":
        return youtube_upload(job, acc)
    if acc["platform"] == "tiktok":
        return tiktok_upload(job, acc, mode=acc.get("tiktok_mode", "draft"))
    if acc["platform"] == "instagram":
        return instagram_upload(job, acc)
    raise ValueError(acc["platform"])


# ---------- Buffer (free plan: public posting to YouTube Shorts / TikTok / IG) ----------
# Buffer's apps are already approved by each platform, so posts go public on day one,
# unlike a self-made YouTube/TikTok API app (private until audited).
BUFFER = "https://api.buffer.com"


def _gql(query, variables=None):
    r = requests.post(BUFFER, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}",
                               "Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {j['errors']}")
    return j["data"]


def buffer_setup():
    """Prints organization + channel ids to paste into config/secrets."""
    load_env()
    orgs = _gql("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        chans = _gql("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service } }",
                     {"o": o["id"]})["channels"]
        out.append({"organization": o, "channels": chans})
    return out


def host_media(path):
    """Public HTTPS URL for the clip. Default: a GitHub release asset on this repo
    (repo must be public), uploaded with the gh CLI that GitHub runners ship with."""
    base = os.environ.get("PUBLIC_MEDIA_BASE_URL")
    if base:  # e.g. an R2/S3 bucket you sync output/ to
        return f"{base.rstrip('/')}/{Path(path).name}"
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("No media host: set PUBLIC_MEDIA_BASE_URL or run inside GitHub Actions")
    import subprocess
    tag = os.environ.get("MEDIA_RELEASE_TAG", "media")
    exists = subprocess.run(["gh", "release", "view", tag, "-R", repo],
                            capture_output=True).returncode == 0
    if not exists:
        subprocess.run(["gh", "release", "create", tag, "-R", repo, "-t", "media",
                        "-n", "Rendered clips (auto)", "--latest=false"],
                       check=True, capture_output=True)
    subprocess.run(["gh", "release", "upload", tag, str(path), "-R", repo, "--clobber"],
                   check=True, capture_output=True)
    return f"https://github.com/{repo}/releases/download/{tag}/{Path(path).name}"


def buffer_post(job, acc):
    url = job.get("media_url") or host_media(job["file"])
    text = job["caption"]
    if acc["platform"] == "youtube":
        # Buffer uses the first line as the Short's title when no YouTube metadata is given
        text = f"{job['title']}\n\n{job['caption']}"
    q = """mutation($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id status dueAt } }
        ... on MutationError { message }
      }}"""
    inp = {"text": text[:4900], "channelId": _env(acc["id"], "BUFFER_CHANNEL_ID"),
           "schedulingType": "automatic", "mode": "customScheduled",
           "dueAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(max(
               time.time() + 120, job.get("due_ts", 0)))),
           "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": 1500}}}]}
    meta = acc.get("buffer_metadata")  # optional per-network metadata from config
    if meta:
        inp["metadata"] = meta
    res = _gql(q, {"input": inp})["createPost"]
    if "post" not in res:
        raise RuntimeError(f"Buffer rejected post: {res.get('message')}")
    return {"buffer_post_id": res["post"]["id"], "media_url": url, "due": res["post"].get("dueAt")}


def buffer_post_info(post_id):
    """Status + external link + metrics. Field names beyond id/status/metrics vary by
    schema version, so the link is requested separately and failures are tolerated."""
    base = _gql("""query($id: PostId!) { post(input: {id: $id}) { id status
                   metrics { name value } } }""", {"id": post_id})["post"]
    for field in ("externalLink", "serviceLink", "link"):
        try:
            d = _gql(f"query($id: PostId!) {{ post(input: {{id: $id}}) {{ {field} }} }}", {"id": post_id})
            if d["post"].get(field):
                base["link"] = d["post"][field]
                break
        except Exception:
            continue
    views = next((m["value"] for m in (base.get("metrics") or [])
                  if str(m.get("name", "")).lower() in ("views", "video views", "plays")), None)
    base["views"] = views
    return base


def draft_upload(tag, path):
    """Upload to a DRAFT release: visible only to people with push access (private review)."""
    import subprocess
    repo = os.environ["GITHUB_REPOSITORY"]
    if subprocess.run(["gh", "release", "view", tag, "-R", repo], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", tag, "-R", repo, "--draft", "-t", tag,
                        "-n", "Private review assets (auto)"], check=True, capture_output=True)
    subprocess.run(["gh", "release", "upload", tag, str(path), "-R", repo, "--clobber"],
                   check=True, capture_output=True)
    return f"draft:{tag}/{Path(path).name}"


def draft_download(ref, dest_dir):
    import subprocess
    tag, name = ref[len("draft:"):].split("/", 1)
    repo = os.environ["GITHUB_REPOSITORY"]
    subprocess.run(["gh", "release", "download", tag, "-R", repo, "-p", name, "-D", str(dest_dir),
                    "--clobber"], check=True, capture_output=True)
    return Path(dest_dir) / name
