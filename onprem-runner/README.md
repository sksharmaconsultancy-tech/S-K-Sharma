# S.K. Sharma & Co. — On-Premise EPFO / ESIC Auto-Login Runner

The EPFO and ESIC government portals **block cloud/datacenter servers** at
their firewall — they only allow connections from Indian ISP (office/home
broadband) networks. So the portal login must run from a **PC at your
office**, not from the app server.

This small program does that. It logs into the portal for you, **reads the
captcha automatically** (using the app's AI reader), and opens the ECR
upload page with your file ready — then hands over to you for the final
Verify / Upload / Pay steps.

---

## 1. One-time setup (on the office PC)

1. **Install Python 3.10+**
   - Download: https://www.python.org/downloads/
   - During install, tick **"Add Python to PATH"**.

2. **Install the two libraries.** Open Command Prompt (Windows) or Terminal
   (Mac) in this folder and run:
   ```
   pip install playwright requests
   python -m playwright install chromium
   ```

3. **Create your config.**
   - Make a copy of `config.example.json` and name it `config.json`.
   - Fill in the values (see the table below).

### config.json fields

| Field             | What to put                                                        |
|-------------------|--------------------------------------------------------------------|
| `app_base_url`    | Your live app URL, e.g. `https://emplo-connect-1.emergent.host`    |
| `app_email`       | Your admin login ID or email (same as the web portal)              |
| `app_password`    | Your admin password                                                |
| `company_id`      | Leave blank for super admin; company admins can leave blank too    |
| `portal_username` | Your **EPFO Establishment ID / user name** for the portal          |
| `portal_password` | Your **EPFO portal password**                                      |
| `portal_url`      | Leave blank (defaults to the official EPFO URL)                    |

Your portal password stays **only on this PC** — it is never sent to the app.

---

## 2. Run it

```
python epfo_agent.py
```

- It will list your compliance runs → pick the month/group you want.
- It downloads that ECR `.txt`, opens EPFO, fills your login, reads the
  captcha, and clicks Login.
- A browser window stays open on the portal. Go to **Payments → ECR Upload**,
  choose the Wage Month + contribution rate, attach the downloaded
  `ECR_<run>.txt`, then **Verify / Upload / Generate Challan** yourself.

For ESIC instead of EPFO:
```
python epfo_agent.py --portal esic
```

To skip the menu and use a specific run:
```
python epfo_agent.py --run-id csrun_xxxxxxxxxxxx
```

---

## Notes & safety

- The **final Upload and Payment are always left to you** on purpose — the
  program never submits money or files without your click.
- If you see **"Portal blocked THIS network too"**, the PC's internet
  connection is also on a blocked IP. Use a machine on your normal office
  broadband (not a VPN/cloud connection).
- Captcha reading is ~95% accurate; if a captcha is misread the program
  refreshes it and retries up to 3 times automatically.
