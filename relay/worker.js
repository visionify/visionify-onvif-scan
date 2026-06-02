// onvif-scan email relay — Cloudflare Worker.
// Holds the Resend API key server-side so it never lives on a client machine
// or in the public CLI repo. Deploy with `wrangler deploy` and set secrets:
//   wrangler secret put RESEND_API_KEY
//   (optional) wrangler secret put RELAY_TOKEN
//
// Then point the CLI at it:  ONVIF_SCAN_RELAY_URL=https://<your-worker>/send

const ALLOWED_DOMAINS = ["visionify.ai"]; // only send to our own people
const FROM = "Onvif Scan <onboarding@visionify.ai>"; // must be a verified Resend sender

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("POST only", { status: 405 });

    // light shared-token check (not a real secret; just keeps randoms out)
    if (env.RELAY_TOKEN) {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.RELAY_TOKEN}`)
        return new Response("unauthorized", { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const to = (Array.isArray(body.to) ? body.to : [body.to]).filter(Boolean);
    const allowed = to.filter((a) =>
      ALLOWED_DOMAINS.some((d) => String(a).toLowerCase().endsWith("@" + d))
    );
    if (!allowed.length)
      return new Response("no allow-listed recipients", { status: 400 });

    const attachments = body.xlsx_base64
      ? [{ filename: body.xlsx_name || "report.xlsx", content: body.xlsx_base64 }]
      : [];

    const resp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: FROM,
        to: allowed,
        subject: body.subject || "Camera onboarding report",
        html: body.html || "<p>(no report body)</p>",
        attachments,
      }),
    });

    const text = await resp.text();
    return new Response(text, { status: resp.status });
  },
};
