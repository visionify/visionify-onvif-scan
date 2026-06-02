# PRD — `onvif-scan`: ONVIF Camera Discovery, Test & Onboarding CLI

**Status:** Draft v0.1
**Author:** Harsh Murari (Visionify)
**Last updated:** 2026-06-02

---

## 1. Problem

When onboarding a new client, we need to figure out — on their network, often over a
short site visit or a single SSH session into a box on their LAN — exactly what cameras
exist and whether each is usable for our computer-vision pipeline. Today this is a manual
nightmare: which devices are ONVIF-capable, what stream URLs they expose, how many
profiles/resolutions each has, the real (not advertised) FPS, the codec, and whether the
image is actually good enough to run analytics on.

We need a single, self-contained CLI we can drop onto any machine on the customer LAN that
**discovers → tests → reports**, producing an artifact we can paste straight into our
onboarding system.

## 2. Goals

- **G1 — One-command discovery.** Find every ONVIF device on the local network(s) and
  persist the list for later use.
- **G2 — One-command testing.** For each device, enumerate its media profiles/streams,
  connect, measure real FPS, capture screenshots, and grade quality.
- **G3 — Onboarding-ready report.** Produce an Excel workbook *and* a self-contained HTML
  report with per-stream resolution, FPS, codec, and screenshot samples.
- **G4 — Easy to run anywhere.** `pipx install` on a remote box; no project checkout needed.
- **G5 — Shareable results.** Email the report to myself via Resend with one flag.

### Non-goals (v1)
- Continuous monitoring / scheduled re-scans (one-shot tool).
- Recording long video clips (we capture sample frames only, ~100 frames).
- Writing to camera config (read-only discovery; we never change camera settings).
- Cloud bucket upload, hosted dashboard, `--serve` web UI (deferred; see §11).
- Cross-subnet routing/VPN orchestration (operator runs us on the right LAN).

## 3. Users & context

- **Primary user:** Visionify field/onboarding engineer (technical, comfortable in a shell).
- **Environment:** A Linux/macOS machine physically or VPN-connected to the customer LAN.
  Often headless, reached via SSH. May be a customer-provided box.
- **Constraints:** Camera credentials are sensitive and vary; some cameras share one
  login (NVR-managed), others are individual. Network may have hundreds of devices.

## 4. End-to-end workflow

```
# on the remote machine, on the customer LAN
pipx install onvif-scan           # one-time

onvif-scan search                 # discover ONVIF devices -> devices.json/.txt
onvif-scan test                   # probe + capture + grade each stream -> results/
onvif-scan report                 # build Excel + HTML from results
onvif-scan report --email         # ...and email it to me via Resend

# or the all-in-one:
onvif-scan run --email            # search -> test -> report -> email
```

All state lives in a working directory (default `./onvif-scan-<date>/`) so a run is fully
resumable and inspectable.

## 5. Commands & CLI surface

> Subcommands chosen over `--search`/`--test` flags for clarity and extensibility, but
> `--search` / `--test` can be kept as aliases if you prefer the original spelling.

### 5.1 `onvif-scan search`
Discover ONVIF devices and persist them.

| Flag | Default | Description |
|---|---|---|
| `--subnet CIDR` | auto-detect | One or more subnets to scan (repeatable). Auto-detects local interfaces if omitted. |
| `--method ws,probe` | `ws,probe` | `ws` = WS-Discovery multicast; `probe` = active TCP probe of ONVIF ports (80/8000/8899/2020…) for devices that don't answer multicast. |
| `--timeout SEC` | `5` | Discovery wait per method. |
| `--out FILE` | `devices.json` | Output device list. Also writes a human-readable `devices.txt`. |
| `--include-non-onvif` | off | Also list cameras that respond to RTSP/HTTP but not ONVIF. |

**Output:** `devices.json` (structured) + `devices.txt` (one `IP  manufacturer  model  onvif-url` per line, easy to eyeball/edit). Operator can hand-edit the txt to add/remove devices before testing.

### 5.2 `onvif-scan test`
Connect to each device, enumerate streams, capture, and measure.

| Flag | Default | Description |
|---|---|---|
| `--devices FILE` | `devices.json` | Device list from `search`. |
| `--frames N` | `100` | Frames to sample per stream for FPS measurement. |
| `--shots N` | `2` | Screenshots saved per stream. |
| `--profiles all` | `all` | `all`, `main`, `sub`, or a max count per camera. |
| `--user U` / `--pass P` | — | Optional. If given, tried first to reduce prompting. |
| `--no-prompt` | off | Never prompt; only use supplied/known/default creds (for unattended runs). |
| `--timeout SEC` | `15` | Per-stream connect/probe timeout. |
| `--workers N` | `4` | Parallel cameras (bounded — cheap NVRs choke under load). |

**Credential model (per your choice — interactive, with smart reuse):**
1. Try `--user/--pass` if provided, else a small built-in list of vendor defaults.
2. On auth failure, **prompt interactively** for that camera (hidden input).
3. **Remember** a working credential and offer it as the default for the next camera
   (`Reuse admin/•••• from 192.168.1.64? [Y/n]`) — so an NVR with 32 identical cameras
   is one prompt, not 32. Credentials are kept **in memory only**, never written to disk
   unless `--save-creds` is explicitly passed (then to a `0600` file).
4. `--no-prompt` skips all prompting for headless/cron use.

**Per stream we record:** profile name/token, RTSP URL, resolution (WxH), codec
(H.264/H.265/MJPEG), advertised FPS, **measured FPS** (frames/elapsed over the sample),
bitrate, GOP/keyframe interval (if available), connect latency, and a quality score (§7).

### 5.3 `onvif-scan report`
Build deliverables from `results/`.

| Flag | Default | Description |
|---|---|---|
| `--format xlsx,html` | both | Which artifacts to emit. |
| `--out DIR` | `./report` | Destination. |
| `--email` | off | Send via Resend (see §8). |
| `--open` | off | Open the HTML report in a browser when done. |

### 5.4 `onvif-scan run`
Convenience: `search → test → report` with the union of the above flags.

## 6. Report contents

### 6.1 Excel (`onboarding-report.xlsx`)
- **Sheet `Summary`:** one row per **device** — IP, manufacturer, model, firmware,
  serial, # of streams, best resolution, best measured FPS, overall status
  (✅ good / ⚠️ usable / ❌ failed), notes.
- **Sheet `Streams`:** one row per **stream** — device IP, profile, resolution, codec,
  advertised FPS, measured FPS, bitrate, RTSP URL, quality score, thumbnail (embedded
  image), screenshot file path/link.
- **Sheet `Failures`:** devices/streams that couldn't be reached, with the reason
  (auth failed, timeout, codec unsupported, no media profile, etc.) — this sheet is the
  real time-saver during onboarding.
- Conditional formatting (green/amber/red) on status and FPS-delta columns.

### 6.2 HTML (`onboarding-report.html`)
- **Self-contained single file** — screenshots embedded as base64 so it survives
  scp/email/Slack with no broken image links.
- Card per device → expandable stream list → thumbnail gallery (click to enlarge),
  metadata table, copy-to-clipboard RTSP URLs.
- Top banner with totals (X devices, Y streams, Z failures) and a filter box.

## 7. Quality scoring (heuristic, transparent)

A 0–100 score per stream so the operator can triage at a glance. Inputs:
- **FPS health:** measured vs advertised (penalize large drops / stutter / variance).
- **Resolution tier:** ≥1080p full credit, scaled down below.
- **Sharpness:** variance-of-Laplacian on a sample frame (blur detection).
- **Exposure:** histogram check for blown-out / near-black frames.
- **Connect reliability:** retries needed, dropped frames during the 100-frame sample.

Score is advisory and every sub-metric is shown, so a human can override. (We are a CV
company — these heuristics are cheap and good enough for onboarding triage.)

## 8. Sharing — email via a relay (no secrets on client machines)

### 8.1 Why a relay, not a baked-in key
We must **not** put the Resend API key in the code: the repo is public, so the key would
be world-readable and Resend auto-revokes keys it finds on GitHub. We also don't want
`.env` files leaving traces on customer machines. The solution that satisfies both:

```
onvif-scan (client box) --HTTPS POST--> onvif-scan relay (serverless) --Resend--> inbox
   ships only the relay URL                 holds RESEND_API_KEY server-side
   (a URL is not a secret)                  (never in repo, never on client)
```

The CLI binary contains **only the relay URL** (not a secret). The Resend key lives solely
in the relay's server-side environment. Benefits: nothing sensitive on the client or in the
repo, key can't be scraped/revoked, central rotation + rate limiting, and the relay doubles
as the optional "store report and return a shareable link" upload feature.

### 8.2 Recipient is configurable (so the whole team can use it)
- `--to addr@x.com` — required-ish; repeatable for multiple recipients.
- Precedence: `--to` flag → `ONVIF_SCAN_EMAIL_TO` env → a small built-in default list
  (e.g. team alias) baked in the CLI so a bare `--email` still goes somewhere sensible.
- `--from-name "Field Eng — Alex"` optional, to identify who ran the scan.
- The relay can enforce an allow-list of recipient domains (e.g. only `@visionify.ai`) so
  the tool can't be repurposed to spam arbitrary addresses.

### 8.3 Behavior
- `--email` sends the HTML report **inline** + the `.xlsx` as an **attachment**.
- Subject auto-includes client + date: `Camera onboarding — <client> — 2026-06-02`.
- Graceful degradation: if the payload is too large to email, the relay stores it and the
  email links to it (shareable URL) instead of failing the run.
- Offline/relay-unreachable: report is still written locally; CLI prints the path and a
  `--email` retry hint.

### 8.4 Relay implementation (separate, private)
- ~30 lines on Cloudflare Workers / Vercel Functions (free tier covers our volume).
- Single `POST /send` endpoint: accepts `{to, subject, html, xlsx_base64}`, validates
  recipient allow-list, calls Resend, optionally stores the bundle and returns a link.
- Lives in a **private** repo or a separate `/relay` dir excluded from the public package.
- Auth on the endpoint: a shared bearer token baked in the CLI is acceptable here (it only
  grants "send a report to an allow-listed address," not access to the Resend key) — or
  leave it open with the domain allow-list + rate limit if simplest.

## 9. Architecture & tech stack

```
onvif_scan/
  cli.py            # Typer/Click entrypoint, subcommands
  discovery/
    wsdiscovery.py  # WS-Discovery multicast (onvif-zeep / wsdiscovery)
    probe.py        # active TCP/RTSP port sweep fallback
  onvif/
    client.py       # GetDeviceInformation, GetProfiles, GetStreamUri
  capture/
    ffprobe.py      # codec/resolution/advertised-fps via ffprobe -of json
    grab.py         # ffmpeg frame grab + measured-FPS sampling
    quality.py      # sharpness/exposure/fps scoring (OpenCV/numpy on grabbed frames)
  report/
    model.py        # dataclasses: Device, Stream, Result
    excel.py        # openpyxl workbook builder
    html.py         # Jinja2 -> single self-contained file
    email.py        # Resend client
  store.py          # working-dir JSON state, resumable
  creds.py          # interactive prompt + in-memory reuse
```

**Key dependencies:** `typer` (CLI), `onvif-zeep` + `wsdiscovery` (ONVIF/discovery),
`ffmpeg`/`ffprobe` (system binary, subprocess), `opencv-python-headless` + `numpy`
(quality metrics on grabbed frames), `openpyxl` (Excel), `jinja2` (HTML), `resend`
(email), `rich` (progress bars / pretty terminal output).

**Concurrency:** bounded thread pool for per-camera I/O; ffmpeg runs as child processes.
Default 4 workers to avoid overwhelming cheap NVRs.

## 9b. Hosting & distribution (internal tool)

Goal: drop onto any client box with the least ceremony, no PyPI account required, repo
stays public. Ranked options:

**→ Recommended: install straight from the public GitHub repo with `pipx`.**
```bash
pipx install "git+https://github.com/visionify/onvif-scan.git"
# pin to a release for reproducibility:
pipx install "git+https://github.com/visionify/onvif-scan.git@v0.3.0"
```
- No PyPI publishing step, no second registry to maintain. `pyproject.toml` in the repo is
  all that's needed. `pipx` isolates dependencies and puts `onvif-scan` on PATH.
- Updates: `pipx upgrade onvif-scan` or re-install pinned to a new tag.
- This is the simplest thing that fully works and matches your "public repo + install
  directly" instinct — just cleaner than `wget`-ing a loose file.

**Alternative A — your `wget` idea, via GitHub Releases.** Build a wheel in CI on tag,
attach it to a GitHub Release, then:
```bash
wget https://github.com/visionify/onvif-scan/releases/download/v0.3.0/onvif_scan-0.3.0-py3-none-any.whl
pipx install ./onvif_scan-0.3.0-py3-none-any.whl
```
Works, gives you versioned artifacts, but it's an extra build/publish step vs. installing
from git. Use this if you want immutable, signed release artifacts.

**Alternative B — one-line bootstrap script.** Host an `install.sh` in the repo that checks
for ffmpeg/pipx and runs the install:
```bash
curl -fsSL https://raw.githubusercontent.com/visionify/onvif-scan/main/install.sh | bash
```
Nicest field UX (handles ffmpeg too), but `curl | bash` is something some customer IT will
balk at — keep the explicit `pipx` command available as the trusted path.

**Public PyPI — not recommended here.** Publishing `onvif-scan` to PyPI makes an internal
tool publicly discoverable/installable and adds release plumbing for no benefit, since
install-from-git already gives you `pip install`. Skip it unless you later want it public.

**Private repo?** Only needed if the *source itself* is sensitive. With the relay design
no secrets live in the code, so the repo can stay public and install stays auth-free. If
you ever go private, install becomes
`pipx install "git+https://<token>@github.com/visionify/onvif-scan.git"`.

**The one system dependency is ffmpeg.** `onvif-scan doctor` detects it and prints the
per-OS install command (`apt install ffmpeg` / `brew install ffmpeg` / static build link).
The optional `install.sh` can install it automatically.

## 10. Data model (persisted JSON)

```jsonc
{
  "client": "Acme Foods",
  "scanned_at": "2026-06-02T18:00:00Z",
  "devices": [{
    "ip": "192.168.1.64", "onvif_url": "http://192.168.1.64/onvif/device_service",
    "manufacturer": "Hikvision", "model": "DS-2CD2143G0", "firmware": "V5.6.3",
    "serial": "…", "reachable": true, "auth": "ok",
    "streams": [{
      "profile": "MainStream", "rtsp_url": "rtsp://…/Streaming/Channels/101",
      "resolution": "2560x1440", "codec": "H264",
      "fps_advertised": 25, "fps_measured": 24.8, "bitrate_kbps": 4096,
      "screenshots": ["shots/192.168.1.64_main_01.jpg", "…_02.jpg"],
      "quality": { "score": 87, "sharpness": 0.74, "exposure": "ok", "frames_dropped": 1 }
    }],
    "error": null
  }]
}
```

## 11. Future / "anything else for onboarding" (deferred, prioritized)

These came out of the brainstorm — not in v1 scope but worth designing toward:

1. **`onvif-scan doctor`** — preflight: ffmpeg present? interfaces/subnets detected?
   multicast allowed? RTSP port reachable? (Cheap to add; high value on customer boxes.)
2. **Self-contained HTML is already the share-anywhere format** — drag into any browser,
   no server. (In v1.)
3. **Cloud link upload** (S3/R2) for a shareable URL — when email attachments are too big
   or you want to send the client a link. (Deferred — needs cloud creds.)
4. **`--serve`** temporary local web UI to browse results live over an SSH tunnel.
5. **Client-branded PDF** summary for handing to the customer (via the existing HTML).
6. **Default-credential audit** — flag cameras still on vendor-default passwords as a
   security finding (nice value-add for the customer).
7. **Re-scan diff** — compare today's run to a prior `devices.json` to show what changed
   (added/removed/degraded cameras) on repeat visits.
8. **Codec/analytics-readiness flags** — e.g. warn on H.265-only cameras if our pipeline
   prefers H.264, or sub-streams below a usable resolution.
9. **CSV export** alongside Excel for systems that ingest CSV.

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cameras don't answer WS-Discovery multicast | Active TCP/RTSP probe fallback (`--method probe`). |
| Advertised FPS lies | We measure real FPS over a 100-frame sample. |
| Cheap NVRs choke on parallel connections | Bounded `--workers`, per-stream timeouts, retries. |
| Mixed/unknown credentials | Interactive prompt + credential reuse + vendor-default attempts. |
| Exotic codecs (H.265, MJPEG) | ffmpeg handles broad codec support; record failures explicitly. |
| Huge networks (100s of cameras) | Streaming progress (rich), resumable state, per-device isolation so one bad camera can't fail the run. |
| Secrets leakage | Creds in memory by default; opt-in `--save-creds` to `0600`; API keys only via env/config, never logged. |

## 13. Milestones

- **M1 — Discovery:** `search` (WS-Discovery + probe) → `devices.json/.txt`. Demo: list devices.
- **M2 — Test core:** ONVIF profile enumeration + ffprobe metadata + ffmpeg screenshot + measured FPS → `results.json`.
- **M3 — Reports:** Excel + self-contained HTML.
- **M4 — Credentials UX:** interactive prompt + reuse + defaults + `--no-prompt`.
- **M5 — Quality scoring:** sharpness/exposure/FPS grade.
- **M6 — Email + packaging:** Resend `--email`, `doctor`, PyPI/pipx, README.

## 14. Open questions

- Repo/package name: `onvif-scan`? (importable module `onvif_scan`.)
- Do you want a `--client "Acme"` flag to stamp the report + email subject? (Assumed yes.)
- Minimum acceptable thresholds (e.g. "fail if measured FPS < 80% of advertised")
  — configurable, but what defaults do you want?
- Should `devices.txt` be the editable source of truth for `test`, or always `devices.json`?
```
