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

## 2026-11-23 run: 0 approved, 1 rejected
- 20261123-005831-c14391 REJECT: Off-game footage (TikTok LIVE phone screen + room cam, no GTA 6 gameplay); no setup->payoff, just shouting about a chatter; captions carry 'I don't give a f***, b****' - not sponsor-safe; filler template hook.
- SYSTEMIC (repeat of 11-22): still no gameplay-presence check - a 'GTA 6 STREAM' titled VOD's pre-game phone/IRL segment passed every compliance check; highlight again starts at 3.0 s (fallback window). Layout facecam_stack used Dom's whole webcam as 'facecam' and the phone screen as 'gameplay'.

## 2026-11-23 run 2: 0 approved, 2 rejected
- 20261123-014924-c96a0a REJECT: Slur in transcript (n-word x2, audio-muted only) plus heavy swearing; not sponsor-safe. Moment (something appears out of nowhere while driving) has no visible setup; generic template hook.
- 20261123-015521-a42e99 REJECT: Slur in transcript (n-word, muted) + 'bitch'; transcript is incoherent fragments with no clear setup->payoff; 3-segment jump-cut edit; generic 'reaction to GTA 6' hook; reaction_score 2.
- SYSTEMIC: slur policy mismatch - engine/edit.py mutes slurs and lets the clip pass (compliance transcript_safe ignores SLUR_RE), but the review bar rejects any clip with a slur; both clips this run wasted a render on it. Engine should hard-skip windows whose transcript matches SLUR_RE. Also highlight start=3.0 fallback window and identical cold_open [9.5,11.2] on both clips (looks hard-coded).

## 2026-11-23 run 3: 0 approved, 2 rejected
- 20261123-035543-a4698d REJECT: Nudity/sexual content: in-game shower scene with a nude character on screen for the whole clip (same scene already rejected as 20261122-055621-9cde81); Dom's commentary ('Scrub, b****') adds nothing - not YouTube/sponsor safe. Filler quote hook.
- 20261123-035716-25a621 REJECT: Crude sexual line captioned ('Suck my f****** nuts'); captions overlap/duplicate ('IT! COME' doubled, 'YOU'RE GONNA' over another line); tow-truck story sequence with no clear setup->payoff; near-duplicate of rejected 20261122-055738-49bb5a (same tow-truck moment and line).
- SYSTEMIC: engine re-renders moments already rejected - both clips this run are the same scenes as 11-22 rejects 9cde81 (nude shower) and 49bb5a (tow truck, 'nuts' line) from the same VOD. Need a rejected-moment memory (VOD url + time window / frame hash) so rejects are never re-queued. Still no nudity/visual safety check; highlight start=3.0 and cold_open [9.5,11.2] fallback again; caption renderer draws overlapping lines.
