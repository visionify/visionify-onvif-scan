# onvif-scan

Discover, test and report on ONVIF cameras on a customer network — built to make
camera onboarding fast. Find every ONVIF device, connect to each stream, measure the
**real** FPS, grab screenshots, grade image quality, and produce an Excel + HTML report
you can drop into onboarding. Optionally email it to your team.

## Edge machine setup

Run these on the machine that sits on the customer's camera network.

```bash
# 1. system deps
sudo apt update && sudo apt install -y ffmpeg pipx        # Debian/Ubuntu
#   macOS:  brew install ffmpeg pipx

# 2. install the tool
pipx install "git+https://github.com/visionify/onvif-scan.git"
pipx ensurepath        # then restart the shell so `onvif-scan` is on PATH

# 3. (optional) enable emailing reports — token shared with you separately
export ONVIF_SCAN_RELAY_TOKEN="<token-shared-separately>"

# 4. verify
onvif-scan doctor
```

The email relay URL is already baked in — no other config needed. Upgrade later with
`pipx upgrade onvif-scan`.

## Use

```bash
onvif-scan doctor                    # check environment
onvif-scan search --client "Acme"    # discover devices  -> ./onvif-scan/
onvif-scan test                      # connect, capture, measure (prompts for creds)
onvif-scan report --email --to you@visionify.ai

# all-in-one
onvif-scan run --client "Acme" --email --to you@visionify.ai
```

Outputs land in `./onvif-scan/`:
- `devices.txt` — editable device list (trim before `test`)
- `results.json` — full structured results
- `shots/` — screenshots
- `onboarding-report.xlsx` — Summary / Streams / Failures sheets
- `onboarding-report.html` — self-contained, share-anywhere report

## Credentials

`test` prompts per camera and **remembers a working login** to reuse on the next camera
(one prompt for a 32-camera NVR). Pass `--user/--pass` to try first, or `--no-prompt`
for unattended runs. Credentials stay in memory — nothing is written to disk.

## Email relay

`--email` POSTs the report to a small Cloudflare Worker that holds the Resend key
server-side — no secrets ever live on an edge machine or in this repo. The relay URL is
baked in (`onvif_scan/config.py`); the optional shared `ONVIF_SCAN_RELAY_TOKEN` is given
to operators separately. The recipient allow-list (in `relay/worker.js`) restricts who
reports can be emailed to. See `relay/README.md` to (re)deploy.

Reports are emailed from `support@palletvision.ai` to allow-listed recipients.
