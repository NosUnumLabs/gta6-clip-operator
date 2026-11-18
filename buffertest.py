#!/usr/bin/env python3
"""End-to-end posting test with a neutral test-pattern video (no third-party footage).
1) introspect Buffer's GraphQL schema (verify field names the operator relies on)
2) host the test video, create a post on the YouTube channel (unlisted/private if supported)
3) poll until published, print the link. The video is deleted afterwards in YouTube Studio."""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.publish import _gql, host_media, buffer_post_info, load_env

load_env()


def t(name):
    q = """query($n:String!){ __type(name:$n){ name kind inputFields{ name type{ name kind ofType{ name kind } } }
           fields{ name type{ name kind ofType{ name kind } } } enumValues{ name } } }"""
    return _gql(q, {"n": name})["__type"]


report = {}
for name in ("CreatePostInput", "PostInputMetaData", "YoutubePostMetadataInput", "PostMetadataInput",
             "Post", "SchedulingType", "ShareMode", "PostStatus"):
    try:
        report[name] = t(name)
    except Exception as e:
        report[name] = f"ERR {e}"
post_t = report.get("Post")
print("Post fields:", [f["name"] for f in (post_t.get("fields") or [])] if isinstance(post_t, dict) else post_t)
for n in ("PostStatus",):
    e = report.get(n)
    print(n, [v["name"] for v in (e.get("enumValues") or [])] if isinstance(e, dict) else e)

# find a YouTube metadata input type and its fields
yt_type, yt_fields = None, []
md = report.get("PostInputMetaData") or {}
for f in (md.get("inputFields") or []) if isinstance(md, dict) else []:
    if "youtube" in f["name"].lower():
        yt_type = f["type"].get("name") or (f["type"].get("ofType") or {}).get("name")
if yt_type:
    yt = t(yt_type)
    yt_fields = [f["name"] for f in yt.get("inputFields") or []]
    print("YouTube metadata type:", yt_type, yt_fields)
    for f in yt.get("inputFields") or []:
        tn = f["type"].get("name") or (f["type"].get("ofType") or {}).get("name")
        if tn and tn[0].isupper() and tn not in ("String", "Boolean", "Int"):
            try:
                e = t(tn)
                if e.get("enumValues"):
                    print(f"  enum {tn}:", [v["name"] for v in e["enumValues"]])
            except Exception:
                pass

# neutral test video
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=12",
                "-f", "lavfi", "-i", "sine=f=440:d=12", "-vf",
                "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                "text='Vicecast engine test - will be deleted':fontsize=48:fontcolor=white:box=1:"
                "boxcolor=black@0.6:x=(w-tw)/2:y=h*0.45",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "vicecast_test.mp4"], check=True)
url = host_media("vicecast_test.mp4")
print("hosted:", url)

inp = {"text": "Vicecast engine test (will be deleted)", "channelId": os.environ["YT_MAIN_BUFFER_CHANNEL_ID"],
       "schedulingType": "automatic", "mode": "customScheduled",
       "dueAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 90)),
       "assets": [{"video": {"url": url}}]}
if yt_type:
    meta = {}
    for k in yt_fields:
        kl = k.lower()
        if kl == "categoryid":
            meta[k] = "20"
        if kl in ("title",):
            meta[k] = "Vicecast engine test (will be deleted)"
        if "privacy" in kl or "visibility" in kl:
            meta[k] = os.environ.get("TEST_PRIVACY", "unlisted")
        if "madeforkids" in kl.replace("_", ""):
            meta[k] = False
        if "notifysubscribers" in kl.replace("_", ""):
            meta[k] = False
    if meta:
        yt_key = next(f["name"] for f in md["inputFields"] if "youtube" in f["name"].lower())
        inp["metadata"] = {yt_key: meta}
print("createPost input:", json.dumps({k: v for k, v in inp.items() if k != "channelId"}))

q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
        ... on PostActionSuccess { post { id status dueAt } }
        ... on MutationError { message } } }"""
try:
    res = _gql(q, {"input": inp})["createPost"]
except Exception as e:
    # privacy enum may want different casing; retry once with uppercase
    print("first attempt failed:", e)
    if "metadata" in inp:
        for v in inp["metadata"].values():
            for k in list(v):
                if isinstance(v[k], str) and k.lower() != "title":
                    v[k] = v[k].upper()
    res = _gql(q, {"input": inp})["createPost"]
print("createPost result:", res)
pid = (res.get("post") or {}).get("id")
if not pid:
    sys.exit("createPost failed: " + str(res))
for i in range(16):
    time.sleep(30)
    try:
        info = buffer_post_info(pid)
        print(f"poll {i}: status={info.get('status')} link={info.get('link')}")
        if info.get("link") or str(info.get("status")).lower() in ("sent", "error"):
            break
    except Exception as e:
        print("poll error:", e)
