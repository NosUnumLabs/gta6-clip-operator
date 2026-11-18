"""Notifications, no extra app needed.

Order of preference:
  1. NTFY_TOPIC set      -> ntfy.sh push (supports exact-time delivery); add NOTIFY_EMAIL
                            to also receive it by email.
  2. inside GitHub Actions -> opens a GitHub issue in this repo. GitHub emails the repo
                            owner (and pushes via the GitHub mobile app) automatically.
  3. otherwise           -> printed to the log.
"""
import datetime as dt, os, subprocess
import requests


def push(title, message, url=None, priority="default", tags="", at=None):
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        headers = {"Title": title.encode("utf-8"), "Priority": priority}
        if url:
            headers["Click"] = url
        if tags:
            headers["Tags"] = tags
        if at:
            headers["At"] = str(int(at))
        if os.environ.get("NOTIFY_EMAIL"):
            headers["Email"] = os.environ["NOTIFY_EMAIL"]
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"),
                          headers=headers, timeout=15)
            return True
        except Exception as e:
            print(f"[notify] ntfy failed: {e}")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        when = ""
        if at:
            when = "\n\n**Goes live:** " + dt.datetime.fromtimestamp(at).astimezone().strftime(
                "%a %b %d, %I:%M %p %Z") + " — submit right after that time."
        body = f"{message}{when}" + (f"\n\n➡️ {url}" if url else "")
        owner = repo.split("/")[0]
        try:
            subprocess.run(["gh", "issue", "create", "-R", repo, "-t", title, "-b", body,
                            "-a", owner], check=True, capture_output=True, timeout=60)
            return True
        except Exception as e:
            print(f"[notify] GitHub issue failed: {e}")
    print(f"[notify] {title}: {message}")
    return False
