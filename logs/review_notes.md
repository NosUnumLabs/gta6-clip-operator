# Reviewer notes

## 2026-11-22 run: 0 approved, 5 rejected
- 20261122-051914-774b0e REJECT: Off-game IRL/just-chatting footage (phone + second-stream screen, no GTA 6 gameplay); no clear moment/payoff; garbled Whisper transcript with race reference ('boy with black people') burned into captions - not sponsor-safe.
- 20261122-052113-342d91 REJECT: No game footage: streamer at desktop browsing a dashboard/chat; no moment, nothing happens; filler quote hook.
- 20261122-055621-9cde81 REJECT: Nudity: in-game shower scene with nude character on screen the whole clip - sexual content, not sponsor/YouTube safe. Also 14.1 s < campaign min 15 s.
- 20261122-055649-f64074 REJECT: No clear moment: static shot of player standing in front of NPC crowd, no setup->payoff, garbled transcript, filler quote hook ('Sure, oh man I got').
- 20261122-055738-49bb5a REJECT: No clear moment: tow-truck footage with no visible payoff by 5 s, weak opening (empty road), crude line ('shock my f****** nuts') captioned; payoff not discernible.
- SYSTEMIC: every highlight has start=3.0 and peak_rel 10-12 (looks like a fixed fallback window, not a detected moment) -> 4/5 clips have no payoff.
- SYSTEMIC: transcript_safe/compliance passed a nude shower scene and off-game desktop/IRL segments; no visual safety or gameplay-presence check. VOD title filter ('gta') lets in non-gameplay segments of GTA-titled streams.
- SYSTEMIC: layout=blurfill with small gameplay + tiny facecam, not the STYLE.md 50/50 split; review renders 774b0e/342d91 already have a hook headline burned in.
