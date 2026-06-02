"""Baked-in defaults. No secrets here — only a relay URL (safe to expose)."""
import os

# Email relay endpoint. The Resend API key lives server-side in the relay,
# never on the client. Override at runtime with ONVIF_SCAN_RELAY_URL if needed.
RELAY_URL = os.environ.get(
    "ONVIF_SCAN_RELAY_URL",
    "https://onvif-scan-relay.palletvision.workers.dev/send",
)

# Optional shared token the relay checks. Set via env so no token value lives in the
# public repo. Empty = rely on the relay's recipient domain allow-list only.
RELAY_TOKEN = os.environ.get("ONVIF_SCAN_RELAY_TOKEN", "")

# Where reports go if --to is not supplied.
DEFAULT_EMAIL_TO = ["onboarding@visionify.ai"]

# Common ONVIF / RTSP / HTTP ports used by the active probe fallback.
PROBE_PORTS = [80, 554, 8000, 8080, 8899, 2020, 8554, 88]

# Vendor default credentials tried before prompting the user.
DEFAULT_CREDENTIALS = [
    ("admin", "admin"),
    ("admin", ""),
    ("admin", "12345"),
    ("admin", "123456"),
    ("admin", "password"),
    ("root", "root"),
]
