# Changelog

All notable project changes are documented in this file.

## v1.0.0 (March 2026)

### New Features

- **New `/transcript` command**
  - Downloads recorded Spaces as MP3
  - Transcribes audio to TXT using faster-whisper
  - Uploads MP3 and TXT back to Discord channel
  - Validates URL format and Space availability
  - Enforces 50MB upload cap per file (Discord limit)
  - Logs audit event for transcript actions

- **New transcription infrastructure**
  - Added `downloader`, `transcriber` modules
  - yt-dlp integration with parallel fragment download
  - faster-whisper integration for automatic transcription
  - WAV 16kHz mono conversion support for Whisper compatibility

### Command Set Changes

- **Removed commands**
  - `/rec` (redundant; `/live` supports live playback flow)
  - `/history`
  - `/historycsv`
  - `/queue`
  - `/skip`
  - `/cq`
  - `/alert_map`
  - `/alert_status`
  - `/alert_check`
  - `/diag` (merged into `/health`)

- **Current slash command set (18 commands synced)**
  - `/live`, `/transcript`, `/participants`, `/dash`, `/dc`, `/mute`, `/resume`
  - `/forward`, `/rewind`, `/mark`, `/now`, `/bookmarks`, `/health`
  - `/alert_add`, `/alert_remove`, `/alert_list`, `/alert_interval`, `/audit_log`

- **Enhanced `/health` command**
  - Replaces legacy `/diag` behavior
  - Shows bot identity, uptime, latency, guild count, voice status, audio status, queue, retries, and channel-status toggle
  - If playback is active: mode (LIVE/REC), title, elapsed, duration, and URL

#### Formatting and Display
- Consolidated DATE format: `DATE: YYYY-MM-DD HH:MM:SS UTC`
- Improved PART format: `PART 1/3` instead of `PART-1-of-3`
- Real final-part time range: last part uses actual end time (not forced to full 1h blocks)
- Minute-range timestamps: `[00:01:00 - 00:02:00]`
- UTF-8 normalization and non-printable character cleanup

#### Performance Optimizations (v1.0)
- Faster download: yt-dlp `--concurrent-fragments 8` (was 4)
- Faster transcription: Whisper `tiny` model (was `base`), `beam_size=1` (was 2)
- Lower audio bitrate: 64kbps (was 96kbps) for faster processing
- Retry tuning: reduced from 10 to 5
- Optimized workflow: transcribe all parts first, then send outputs in batch

#### UX Improvements (v1.0)
- Simplified user-facing messages
  - Final status message only for completion
  - Consolidated progress updates by part and percentage
  - Final summary with total transcribed segments
- Sends transcript outputs together after processing completes

#### Code Refactoring
- Consolidated `extract_space_id()` logic into shared utility handling `/spaces/` and `/i/spaces/`
- Consolidated filename sanitization into shared utility (`build_filename_from_display_label` / `safe_filename` path)
- Removed duplicated short-info builders by reusing `_build_display_label()`
- Fills minute gaps in transcript timeline (including VAD-removed silent windows)

#### Error Handling
- Token-expiration resilience: fallback from interaction webhook responses to `channel.send()` when needed
- Attachment safety: avoids passing `file=None` into Discord SDK

### Dependencies

- Added: `faster-whisper>=1.0.0`
- System requirement: `ffmpeg`

---

## v0.2.0 (March 2026)

### New Features

- **New `/participants` command**
  - Scrapes participants for current Space
  - Shows host, co-hosts, speakers, and listeners
  - Includes direct links to X profiles

- **Bookmark improvements**
  - `/mark` accepts optional title
  - Position is computed from real UTC start time to bookmark timestamp
  - Shows Space start UTC and bookmark UTC

- **Expanded `/bookmarks` command**
  - `action:list` — list bookmarks
  - `action:delete bookmark_id:<id>` — delete one
  - `action:clear` — clear all

### Significant Changes

- Removed commands: `/pause`, `/seek`, `/seekback`, `/seekto`
- Removed panel buttons: Pause, -1m, -5m, +5m, +30m, +1h, Seek, Clear chat
- Focus shifted to X Spaces only (YouTube support removed)
- Scraper configuration moved to environment variables

---

## v0.0.3 (March 2026)

### Validations and Behavior

- Strict URL validation: only `https://x.com/i/spaces/<id>` accepted
- Improved voice behavior: bot joins voice channel deafened
- Idle auto-disconnect: leaves voice if alone for 5 minutes
- Auto-stop on Space end: leaves voice and posts summary (title, host, participants, listeners, duration, URL)

---


### User Attribution Across Actions

All critical actions now store who executed them, when, and what was changed:

- `/live` records who started playback and URL
- `/mark` stores who created each bookmark
- `/bookmarks action:delete|clear` records who modified bookmarks
- `/alert_add`, `/alert_remove` records alert-management actions
- `/transcript` records transcript processing actions

### New `/audit_log` Command

- Shows recent administrative events
- Supports filtering by event type (`bookmark_add`, `alert_remove`, etc.)
- Shows user, timestamp, resource ID/name, and details