# Setup — about 30 minutes, once

After this, the operator runs by itself every 30 minutes. Your ongoing part: tap
"Submit" when a campaign push arrives (only for paid campaign clips) and tell
Claude about campaigns you join.

## 1. GitHub (runs the operator for free)
1. Create a free GitHub account if needed.
2. New repository → **Public** (public repos get unlimited free Actions minutes, and
   the clip files are hosted as release assets so Buffer can fetch them).
3. Upload this folder's contents (or let Claude push it if you attach the repo).
4. Settings → Actions → General → Workflow permissions → **Read and write**.

## 2. Buffer (posts to YouTube publicly — free plan, 3 channels)
1. Sign up at buffer.com (free plan). Connect the YouTube channel @metamanarmor4675.
2. Settings → API → create a personal API key.
3. In GitHub: Settings → Secrets and variables → Actions → New secret:
   - `BUFFER_API_KEY` = the key
4. Get the channel id: Actions tab → run the workflow once with `OPERATOR_LIVE=false`
   (Settings → Variables), or locally run `python3 run.py buffer-setup`.
   Add secret `YT_MAIN_BUFFER_CHANNEL_ID`.

## 3. Phone alerts (free)
1. Install the **ntfy** app. Subscribe to a long random topic, e.g. `gta6-ops-7f3k9q2m`.
2. GitHub secret `NTFY_TOPIC` = that topic.
You'll get: "SUBMIT NOW" alerts for campaign clips, a daily digest, and failures.

## 4. YouTube Data API key (free; lets the learner read views and scan trends)
Google Cloud console → new project → enable "YouTube Data API v3" → Credentials →
API key. GitHub secret `YT_API_KEY`. (Read-only; no OAuth or audit needed.)

## 5. Content Rewards / Vyro (where the money comes from)
1. Sign up at contentrewards.com (payouts via Whop) and/or vyro.com.
2. Link the YouTube channel inside Content Rewards (Profile → Linked Accounts).
   Accounts linked only inside Whop do not count.
3. Join campaigns that allow **YouTube** and name GTA 6 streams. Send Claude the
   campaign link; it becomes an entry under `campaigns:` in config.yaml.

## Turning it on
Settings → Variables → `OPERATOR_LIVE` = `true` (or delete it). Watch the Actions tab:
each run commits its state (`queue/`, `state/`, `logs/engine.log`).

## Safety switches
- `OPERATOR_LIVE=false` → everything runs, nothing posts.
- Disable the workflow (Actions → clip-operator → ⋯ → Disable) → full stop.
- `campaigns[].active: false` → stop clipping that campaign's sources.
