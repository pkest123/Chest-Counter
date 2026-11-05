# Chest Counter Classic

A Windows desktop counter for visible Fortnite chest notifications. It runs
locally, preserves your session count, and shows PC and app CPU/RAM usage.

## Run the Windows app

Download **ChestCounter-Classic-Windows.zip** from this repository's Releases,
extract the whole ZIP, and open `ChestCounter/ChestCounter.exe`. Keep `_internal`
beside the executable. Python does not need to be installed.

Press **Start watching**. Automatic mode scans the selected display regardless
of which app has focus. Choose the display in Advanced settings. To open the
counter window on monitor 2, run `ChestCounter.exe --second-monitor`; window
placement is remembered separately from the capture display.

## Notification accuracy update

- Learns a small notification area from a recognized chest completion, then
  rereads it faster with the same OCR model sessions.
- Keeps up to eight seconds of small-area frames in memory to recover brief
  notifications seen during a slower full-display recheck.
- Handles completion wording, split XP fragments, joined words, and a common
  `CHE5T` OCR substitution.
- Uses shorter notification rearming while rejecting brief flicker and
  repeated readings of the same lingering notification.
- Excludes search prompts, quest progress sentences and generic
  `CONTAINER OPENED` sprite messages.

Use **Advanced settings → Re-scan full display** after changing the HUD layout
or if the learned area is wrong. No notification area is known on the first
run, so discovery initially uses the slower full-display scan.

## Controls

| Control | Action |
| --- | --- |
| Start watching / Pause | Start or stop detection |
| Add +1 / Undo last | Correct the count |
| Reset | Clear the current session after confirmation |
| Export CSV | Save event timestamps and detection sources |
| Advanced settings | Capture display, manual area and phrase, optional visual reference |

The usage panel updates once a second with total PC CPU/physical RAM usage and
the counter's own CPU/working-set RAM usage.

## Limits

This is a notification detector, not a trained chest-object recognizer. It
cannot guarantee every chest or reliably infer a broken chest when no readable
notification appears. Merged or overlapping toasts, severe OCR errors, heavy
load, and notifications outside the learned area can still cause misses. Other
apps on the watched display can affect counts if they show matching text.
Full-display discovery and rechecks can use noticeable CPU and affect games.

Automated checks cover rapid notifications, slow-scan rearming, OCR flicker,
completion variations, spatial XP fragments, focus coordinates and rejection
of prompts/quests/sprite messages. Controlled integration checks also exercised
area learning and recovery of brief toasts during a simulated slow scan.
Repeated live gameplay accuracy for this update is not established.

## Privacy and saved data

No account, API key, microphone or cloud processing is used. Screen frames stay
in memory and are not continuously recorded. The explicitly selected optional
visual reference is saved locally. Counts, settings, references and latest
diagnostics live in `%LOCALAPPDATA%/FortniteChestCounter` for the packaged app.
The source version uses its local `data/` folder. None of that personal data is
included in this repository or the release archive.

## Run from source

Requires Windows and Python 3.11. Double-click `Start.cmd`, or:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Tests and Windows build

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\Build.ps1
```

The build script creates `dist/ChestCounter/` and
`dist/ChestCounter-Classic-Windows.zip`. The large Windows archive belongs in
GitHub Releases rather than the Git source history.
