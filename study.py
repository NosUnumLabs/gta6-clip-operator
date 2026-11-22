"""Post-launch market study: top GTA 6 Shorts since launch, with engagement stats + thumbnails.
Writes study_out/study.json + thumbs/*.jpg (uploaded to a private draft release)."""
import os, json, re, datetime as dt, requests
from pathlib import Path
K = os.environ["YT_API_KEY"]; B = "https://www.googleapis.com/youtube/v3"
out = Path("study_out"); (out / "thumbs").mkdir(parents=True, exist_ok=True)
since = "2026-11-19T00:00:00Z"
queries = ["gta 6", "gta 6 funny", "gta 6 streamer", "gta 6 clips", "gta 6 kai cenat", "gta 6 xqc",
           "gta 6 reaction", "gta 6 police", "gta 6 fail", "gta 6 physics", "gta vi", "gta 6 moments",
           "gta 6 tomo", "gta 6 dasgas"]
ids = {}
for q in queries:
    for order in ("viewCount", "relevance"):
        r = requests.get(f"{B}/search", params=dict(key=K, part="id", q=q, type="video", videoDuration="short",
                         publishedAfter=since, order=order, maxResults=50)).json()
        for it in r.get("items", []):
            ids.setdefault(it["id"]["videoId"], q)
vids = list(ids)
rows = []
for i in range(0, len(vids), 50):
    r = requests.get(f"{B}/videos", params=dict(key=K, part="snippet,statistics,contentDetails",
                     id=",".join(vids[i:i+50]))).json()
    for v in r.get("items", []):
        d = v["contentDetails"]["duration"]; m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", d)
        secs = int(m.group(1) or 0) * 60 + int(m.group(2) or 0) if m else None
        if not secs or secs > 180: continue
        st = v["statistics"]; sn = v["snippet"]
        pub = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        age_h = max(1, (dt.datetime.now(dt.timezone.utc) - pub).total_seconds() / 3600)
        views = int(st.get("viewCount", 0))
        rows.append(dict(id=v["id"], title=sn["title"], channel=sn["channelTitle"], published=sn["publishedAt"],
                         secs=secs, views=views, likes=int(st.get("likeCount", 0)), comments=int(st.get("commentCount", 0)),
                         vph=round(views / age_h), tags=sn.get("tags", [])[:12], desc=sn.get("description", "")[:300],
                         thumb=sn["thumbnails"].get("maxres", sn["thumbnails"].get("high", {})).get("url"), q=ids[v["id"]]))
rows.sort(key=lambda x: -x["vph"])
for r in rows[:40]:
    try:
        open(out / "thumbs" / f"{r['id']}.jpg", "wb").write(requests.get(r["thumb"], timeout=20).content)
    except Exception: pass
# channel sizes for top 40 (is it the streamer, a big clipper, or a small clipper?)
chs = {}
r = requests.get(f"{B}/videos", params=dict(key=K, part="snippet", id=",".join(x["id"] for x in rows[:50]))).json()
cid = {v["id"]: v["snippet"]["channelId"] for v in r.get("items", [])}
cs = requests.get(f"{B}/channels", params=dict(key=K, part="statistics", id=",".join(set(cid.values())))).json()
subs = {c["id"]: int(c["statistics"].get("subscriberCount", 0)) for c in cs.get("items", [])}
for x in rows[:50]: x["channel_subs"] = subs.get(cid.get(x["id"]))
json.dump(rows, open(out / "study.json", "w"), indent=1)
print(len(rows), "shorts")
