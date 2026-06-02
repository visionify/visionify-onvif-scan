# onvif-scan email relay

A ~40-line Cloudflare Worker that emails onboarding reports via Resend while keeping the
Resend API key server-side. The CLI only knows the relay URL (not a secret).

## Deploy

```bash
npm i -g wrangler
cd relay
wrangler deploy worker.js --name onvif-scan-relay
wrangler secret put RESEND_API_KEY      # paste your Resend key
wrangler secret put RELAY_TOKEN         # optional shared token
```

Edit `ALLOWED_DOMAINS` and `FROM` in `worker.js` (the `FROM` address must be a verified
Resend sender/domain). Then point the CLI at it:

```bash
export ONVIF_SCAN_RELAY_URL="https://onvif-scan-relay.<you>.workers.dev/send"
export ONVIF_SCAN_RELAY_TOKEN="...same token..."   # if you set one
```

Keep this `relay/` directory in a **private** repo (or exclude it from the public CLI
package). It contains no secret itself, but there's no reason to publish it.
