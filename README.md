# onvif-scan

Discover, test and report on ONVIF cameras on a customer network — built to make
camera onboarding fast. Find every ONVIF device, connect to each stream, measure the
**real** FPS, grab screenshots, grade image quality, and produce an Excel + HTML report
you can drop into onboarding. Optionally email it to your team.

## Install

```bash
pipx install "git+https://github.com/visionify/onvif-scan.git"
# needs ffmpeg on the host:  brew install ffmpeg   |   apt install ffmpeg
```

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

`--email` POSTs the report to a small serverless relay that holds the Resend key
server-side. No secrets ever live on the client or in this repo. See `relay/` for the
~30-line Cloudflare Worker. Set `ONVIF_SCAN_RELAY_URL` to point at your deployment.
