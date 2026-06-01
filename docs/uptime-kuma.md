# Uptime Kuma - PHAEMOS Status Monitoring

Uptime Kuma is a self-hosted monitoring tool used to track uptime for the PHAEMOS backend and frontend services.

---

## 1. Self-hosted deployment (Docker)

```bash
docker run -d \
  --name uptime-kuma \
  --restart always \
  -p 3001:3001 \
  -v uptime-kuma:/app/data \
  louislam/uptime-kuma:1
```

Access the dashboard at `http://localhost:3001` and complete the one-time admin setup.

---

## 2. Monitor configuration

### Backend (Render)

| Field       | Value                                          |
|-------------|------------------------------------------------|
| Type        | HTTP(S)                                        |
| URL         | `https://<your-render-service>.onrender.com/`  |
| Interval    | 60 seconds                                     |
| Keyword     | `ok` (matches the JSON health response)        |
| Name        | PHAEMOS API                                    |

The backend health endpoint returns `{"status": "ok", ...}` — use keyword matching on `ok` to confirm the service is alive and not just returning a 200 from a CDN cache.

### Frontend (Vercel)

| Field    | Value                                      |
|----------|--------------------------------------------|
| Type     | HTTP(S)                                    |
| URL      | `https://<your-vercel-domain>.vercel.app/` |
| Interval | 60 seconds                                 |
| Name     | PHAEMOS Dashboard                          |

---

## 3. Discord webhook notifications

1. In your Discord server, go to **Server Settings > Integrations > Webhooks**.
2. Create a new webhook in your `#alerts` (or `#status`) channel and copy the URL.
3. In Uptime Kuma: **Settings > Notifications > Add new notification**.
4. Select **Discord** as the type and paste the webhook URL.
5. Assign the notification to both monitors.

Uptime Kuma will post a message to Discord when a monitor goes down or recovers.

---

## 4. Status page (optional)

1. In Uptime Kuma, go to **Status Pages > New Status Page**.
2. Add both monitors (API and Dashboard).
3. Publish the page and copy the public URL.
4. Add a "Status" link to the PHAEMOS frontend footer pointing to this URL.

---

## 5. Tips

- Set a **heartbeat timeout** of 90 seconds for Render monitors - Render's free tier spins down after inactivity and the first request can take up to 50 seconds to respond.
- Enable **TLS/SSL certificate expiry** alerts (Uptime Kuma checks this automatically for HTTPS monitors).
- Add the status page URL to `docs/deployment.md` for reference.
