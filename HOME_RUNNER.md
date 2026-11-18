# Home runner (one-time, ~10 minutes)

Lets the operator process campaigns whose footage sits on YouTube (e.g. Tomo).
YouTube blocks downloads from GitHub's data centers but not from a home connection.
The computer must stay on and online; it does nothing except when a job arrives.

## Requirements
- Windows 10/11, macOS or Linux, always on (disable sleep)
- Python 3.10+  ·  ffmpeg  ·  Git (on Windows: "Git for Windows", which includes bash)

Windows quick install (PowerShell as admin):
```
winget install Python.Python.3.12 Gyan.FFmpeg Git.Git
```
macOS: `brew install python ffmpeg git`

## Register the runner
1. GitHub → NosUnumLabs/gta6-clip-operator → Settings → Actions → Runners → **New self-hosted runner**.
2. Pick your OS and run the commands shown there **exactly** (they contain a one-time token).
3. When `config` asks for **labels**, type: `home`
4. Install it as a service so it survives reboots:
   - Windows: answer **Y** to "run as service" during config.
   - macOS/Linux: `./svc.sh install && ./svc.sh start`
5. Back in GitHub: Settings → Secrets and variables → Actions → Variables → add `HOME_RUNNER` = `true`.

That's it. Each cycle the cloud job runs first, then the home job handles the `runner: home` campaigns.
