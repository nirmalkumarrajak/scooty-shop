# 🚀 Deploy ScootyBazaar to Render (Free)

Free hosting with **custom domain** + **automatic HTTPS** + **no credit card**.

---

## ⚠️ READ THIS FIRST — Free Tier Limitations

Render's free tier uses an **ephemeral filesystem**:
- SQLite database resets on every deploy / periodic restart → **user registrations & product edits reset to seeded defaults**
- Admin-uploaded images disappear after restarts
- App **sleeps after 15 min of inactivity** → first visit takes ~30-50 seconds to wake up

For a demo / small shop that runs on WhatsApp orders, this is usually fine.
For real persistence, see "Making it permanent" at the bottom.

---

## Step 1 — Put your code on GitHub

1. Create a free GitHub account: https://github.com/signup
2. Install Git: https://git-scm.com/downloads (Windows) — already installed on Mac/Linux
3. Open a terminal inside the `scooty_shop` folder and run:

```bash
git init
git add .
git commit -m "Initial commit"
```

4. Go to https://github.com/new, create a repo named `scooty-shop` (keep it empty — no README)
5. Copy the two commands GitHub shows and run them (they look like):

```bash
git remote add origin https://github.com/YOUR_USERNAME/scooty-shop.git
git branch -M main
git push -u origin main
```

Your code is now on GitHub ✓

---

## Step 2 — Deploy on Render

1. Go to https://render.com and click **"Get Started for Free"**
2. Sign up with your GitHub account (one click — no credit card asked)
3. On the dashboard click **"+ New"** → **"Web Service"**
4. Choose **"Build and deploy from a Git repository"** → **"Next"**
5. Find your `scooty-shop` repo in the list → click **"Connect"**
6. Fill in the form:

| Field | Value |
|---|---|
| Name | `scooty-shop` (or anything) |
| Region | Singapore (closest to India) |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |
| Instance Type | **Free** |

7. Scroll down → **"Advanced"** → **"Add Environment Variable"**:
   - Key: `SECRET_KEY`
   - Value: any random long string (e.g. `xK9mP2vQ8nR5tY7wL3jH6fD1aS4bC0eG`)

8. Click **"Create Web Service"**

Render will build and deploy your app. Takes 2–4 minutes the first time.
You'll get a free URL like `https://scooty-shop.onrender.com` — test that it works first!

---

## Step 3 — Connect YOUR custom domain

Let's say your domain is **`myshop.in`**. You want visitors to see your site at `www.myshop.in` (or just `myshop.in`).

### 3a. On Render
1. Go to your service → **"Settings"** tab → scroll down to **"Custom Domains"**
2. Click **"Add Custom Domain"** → type `www.myshop.in` → **Save**
3. Render shows you a CNAME target like `scooty-shop.onrender.com` — **copy it**
4. Add another custom domain `myshop.in` (the apex/root) — Render gives an A-record IP or redirect instruction

### 3b. On your domain registrar (GoDaddy, Namecheap, Hostinger, BigRock, etc.)

Open DNS management for your domain and add these records:

| Type | Name / Host | Value / Points to | TTL |
|---|---|---|---|
| **CNAME** | `www` | `scooty-shop.onrender.com` (use what Render showed you) | 3600 |
| **A** | `@` (or blank) | (use the IP Render provides — usually `216.24.57.1`) | 3600 |

**Delete** any old A, AAAA, or CNAME records that conflict for `www` and `@`.

### 3c. Wait + verify
- DNS propagation takes **5 minutes to 2 hours** (sometimes up to 24h)
- Check https://dnschecker.org with your domain
- Render auto-issues a free SSL certificate once DNS resolves → you'll see a green ✓ on the custom domain row

Open `https://www.myshop.in` — your ScootyBazaar is live! 🎉

---

## Step 4 — Pushing updates later

Whenever you change your code:
```bash
git add .
git commit -m "updated product descriptions"
git push
```
Render auto-redeploys within 1–2 minutes. (Remember: this wipes the SQLite DB.)

---

## Making it permanent (optional, small cost)

If you want user accounts and admin edits to survive across restarts:

**Cheapest option (~$7/month total):**
1. Add a **Render Persistent Disk** (1 GB for ~$1/mo) — mount it at `/var/data`, move `database.db` and `static/images/` there
2. OR upgrade to Render's Starter plan ($7/mo) — no sleep, persistent disk included

**Proper production option (free for 90 days, then ~$7/mo):**
1. Use Render's **free PostgreSQL** add-on instead of SQLite
2. Use **Cloudinary free tier** for image uploads (25 GB free forever)

Ask me if you want help migrating — I can update the code.

---

## Alternative: PythonAnywhere (simpler but no free custom domain)

PythonAnywhere is easier to set up (no Git needed — just upload files), but on the free tier you're stuck with `yourusername.pythonanywhere.com` — custom domains require their $10/month Developer plan. Since you already have a domain, **Render is the right choice**.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Application failed to respond" | Check Render logs tab — usually a missing env var or wrong start command |
| Custom domain shows "Certificate pending" forever | Your DNS isn't resolving yet — wait longer, or check records at dnschecker.org |
| Images disappear after a few hours | Expected on free tier (ephemeral disk) — see "Making it permanent" |
| App is slow on first request | Free tier sleeps after 15 min idle — upgrade to Starter plan to fix |
