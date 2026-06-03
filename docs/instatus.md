# Status Page - Instatus Setup

Phaemos uses [Instatus](https://instatus.com) to host the public status page at `status.phaemos.com`. Instatus is hosted independently of the VPS - if the VPS goes down, the status page remains reachable.

---

## 1. Create the Instatus account and status page

1. Sign up at [instatus.com](https://instatus.com) (free tier is sufficient).
2. Click **Create status page** and name it **Phaemos Status**.
3. Set the page language to English.

---

## 2. Add components

Add two components to track the main platform surfaces:

| Component name | Monitor type | URL | Check interval |
| --- | --- | --- | --- |
| Platform | HTTP | `https://phaemos.com` | 60 seconds |
| API | HTTP with keyword | `https://api.phaemos.com/health` | 60 seconds |

For the API component, enable **Keyword monitoring** and set the keyword to `ok`. The health endpoint returns `{"status":"ok",...}` when all services are healthy - keyword matching confirms the backend is genuinely responding, not just returning a 200 from a proxy cache.

---

## 3. Custom domain (status.phaemos.com)

1. In the Instatus dashboard, go to **Settings** -> **Domain**.
2. Enter `status.phaemos.com` as the custom domain.
3. Instatus displays a CNAME target (e.g. `yourpage.instatus.com`).
4. Add a DNS record in your provider (Cloudflare or DigitalOcean DNS):

```text
status  CNAME  yourpage.instatus.com
```

5. Click **Verify** in Instatus. Propagation takes up to 15 minutes.

---

## 4. Notifications

Under **Settings** -> **Notifications**, configure at minimum:

- **Email** - add `dev@phaemos.com` so incidents trigger an email alert
- **Slack** or **Discord** - paste the incoming webhook URL from your team channel

---

## 5. Incident workflow

When a monitor goes down, Instatus automatically creates a new incident and updates the status page. For planned maintenance:

1. Go to **Incidents** -> **New maintenance**.
2. Set the scheduled window and affected components.
3. Instatus notifies subscribers automatically.

For unplanned incidents, update the incident status (Investigating / Identified / Monitoring / Resolved) manually as you work through the issue. Subscribers receive an update for each status change.

---

## 6. Subscriber notifications

Instatus allows visitors to subscribe to status updates via email. Encourage users to subscribe by linking to `status.phaemos.com` from:

- The `/support` page in the dashboard
- The `/status` page internal banner
- Incident-related emails sent from `support@phaemos.com`
