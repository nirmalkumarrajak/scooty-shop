# 🛵 ScootyBazaar — Flipkart-style Flask E-commerce

Flipkart-inspired e-commerce for scooters & accessories (Flask + SQLite).
Orders go to **WhatsApp +91 8789899421**.

Three user roles:
- 🛒 **Customer** — browse & buy via WhatsApp
- 🏪 **Vendor** — register a shop, list your own products
- 🔐 **Admin** — HIDDEN access via username + password

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt
python app.py
```
Open **http://127.0.0.1:5000**

---

## 🔑 Login Info

### 🛒 Customer
Click "Login" → "Create an account".

### 🏪 Vendor (demo account)
- URL: **http://127.0.0.1:5000/vendor/login**
- Username: `scootybazaar`
- Password: `vendor123`

Or register at **"Become a Seller"**.

### 🔐 Admin (HIDDEN — no button in UI)
1. Type **http://127.0.0.1:5000/portal** directly in your browser
2. Login with:
   - Username: `admin`
   - Password: `nirmal123456`
3. You're in!

### 🔑 Changing the admin password
Once logged in as admin, click **"🔑 Change Password"** at the top of the dashboard.
Enter the current password (`nirmal123456`) and pick a new one. After saving, you'll be logged out and must login again with the new password.

---

## 🏪 How Vendors Work

1. Sign up at `/vendor/register` → business name, phone, address
2. Login → **Vendor Dashboard** with stats
3. Add/edit/delete **only their own products** (multi-image gallery supported)
4. Products show "Sold by: [Business Name]" on the homepage
5. Buy button routes orders to ScootyBazaar's main WhatsApp

**Admins** can edit ANY vendor's products.

---

## 🗑️ Delete `database.db` before running!

The schema changed (OTP table removed). Delete the old DB so the app recreates it:

```
del database.db        (Windows)
rm database.db         (Mac/Linux)
```

This also resets the admin password back to `nirmal123456`.

---

## 📁 Structure

```
scooty_shop/
├── app.py                     # Flask routes & DB logic
├── requirements.txt           # Flask, Werkzeug, gunicorn
├── Procfile, runtime.txt      # For Render deployment
├── DEPLOY.md                  # Free hosting guide
├── setup_and_run.bat / .sh    # Local setup scripts
├── static/
│   ├── css/style.css
│   └── images/                # Product images
└── templates/
    ├── base.html              # Layout (navbar hides admin link)
    ├── index.html             # Homepage
    ├── _product_card.html
    ├── product_detail.html    # Image gallery + buy
    ├── product_form.html      # Shared admin/vendor add-edit form
    ├── register.html / login.html                  # Customer auth
    ├── vendor_register.html / vendor_login.html / vendor_dashboard.html
    ├── portal.html                    # HIDDEN admin login
    ├── admin_change_password.html     # Admin password change
    ├── admin_dashboard.html
    └── 404.html
```

---

## ⚠️ Production Checklist

Before going live:
1. Set `SECRET_KEY` via env variable (random long string)
2. Change `ADMIN_PORTAL_PATH` in app.py to something secret (e.g., `/xk9z-admin`)
3. Login as admin and **change the password** from `nirmal123456`
4. See **DEPLOY.md** for free Render hosting with your custom domain

### Render Environment Variables (only 1 needed now)

| Key | Value |
|---|---|
| `SECRET_KEY` | a long random string, e.g. `xK9mP2vQ8nR5tY7wL3jH6fD1aS4bC0eG` |

No SMTP / OTP / email variables are needed anymore.
