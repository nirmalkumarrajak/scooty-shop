"""
ScootyBazaar - A Flipkart-style e-commerce website for scooters & accessories.
Built with Flask + SQLite. Buying redirects to WhatsApp: +91 8789899421

Features:
- Customer registration & login
- Admin login (username: admin, password: admin123)
- Product catalog (scooters + accessories) with categories
- Admin can add / edit / delete products (name, price, description, image, stock)
- Buy button opens WhatsApp chat with seller
- Product search
"""

import os
import sqlite3
from urllib.parse import quote
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ----------------------------- CONFIG ---------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

# >>> Seller's WhatsApp number (country code 91 for India). Change if needed.
WHATSAPP_NUMBER = "918789899421"

# >>> Hidden URL for admin access. Change this to something secret in production.
ADMIN_PORTAL_PATH = "/portal"

# >>> Default admin credentials (only used on FIRST run to seed the DB).
#     After first login, admin can change this via "Change Password" in the panel.
#     Once the DB has an admin user, this variable is ignored.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "nirmal123456"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-in-production-please")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload cap


# ----------------------------- DATABASE -------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables & seed initial data if the DB is empty."""
    need_seed = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password      TEXT NOT NULL,
            phone         TEXT,
            role          TEXT DEFAULT 'customer',   -- 'customer' | 'vendor' | 'admin'
            business_name TEXT,
            business_address TEXT,
            approved      INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL,          -- 'scooter' or 'accessory'
            brand       TEXT,
            price       REAL NOT NULL,
            old_price   REAL,
            description TEXT,
            image       TEXT,                   -- PRIMARY image filename (used on cards)
            stock       INTEGER DEFAULT 10,
            rating      REAL DEFAULT 4.2,
            vendor_id   INTEGER DEFAULT 1,      -- who listed this product (user.id)
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS product_images (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL,
            filename    TEXT NOT NULL,
            sort_order  INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # ---- Seed admin + sample vendor + sample products only on first run ----
    if need_seed or cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        # Admin user (id=1). Change password later via "Change Password" in admin panel.
        cur.execute(
            "INSERT OR IGNORE INTO users (username, email, password, phone, role, business_name) "
            "VALUES (?, ?, ?, ?, 'admin', ?)",
            (DEFAULT_ADMIN_USERNAME, "admin@scootybazaar.com",
             generate_password_hash(DEFAULT_ADMIN_PASSWORD), WHATSAPP_NUMBER, "ScootyBazaar HQ")
        )
        # Sample vendor account (id=2) for the demo data
        cur.execute(
            "INSERT OR IGNORE INTO users (username, email, password, phone, role, business_name, business_address) "
            "VALUES (?, ?, ?, ?, 'vendor', ?, ?)",
            ("scootybazaar", "seller@scootybazaar.com",
             generate_password_hash("vendor123"), "919999999999",
             "ScootyBazaar Authorised Seller", "MG Road, New Delhi - 110001")
        )
        conn.commit()

    if cur.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        sample = [
            # The red scooter from your uploaded image (has 4 gallery images)
            ("Thunder Bolt X1 Electric Scooter", "scooter", "ScootyBazaar",
             94999, 114999,
             "The Thunder Bolt X1 is our flagship electric scooter built for modern Indian cities. "
             "Powered by a 3.0 kWh Lithium-ion battery, it delivers a certified range of 120 km on a "
             "single charge and a top speed of 85 km/h. Features include a full-LED smart headlamp, "
             "digital TFT cluster with Bluetooth turn-by-turn navigation, reverse assist, 3 riding modes "
             "(Eco / City / Sport), keyless start, and anti-theft GPS. Ruby-red metallic paint, alloy wheels, "
             "and a spacious under-seat storage that fits a full-face helmet. Fast-charges 0-80% in 2.5 hours.",
             "scooter_red.png", 15, 4.6),

            ("Urban Glide 110 Petrol Scooter", "scooter", "ScootyBazaar",
             78500, 82000,
             "A reliable 110cc petrol scooter perfect for daily commute. Fuel-injected BS6 engine delivers "
             "55 kmpl mileage. Telescopic front suspension, tubeless tyres, USB charging port, "
             "and a 22-litre under-seat storage.",
             None, 22, 4.3),

            ("EcoRide Zap 2.0 Electric Moped", "scooter", "ScootyBazaar",
             64999, 69999,
             "Compact, lightweight electric moped ideal for students and short city trips. 70 km range, "
             "removable battery that you can charge indoors. Speeds up to 45 km/h — no license required "
             "(as per Indian EV norms for low-speed vehicles). Available in 4 colours.",
             None, 30, 4.1),

            ("RoadMaster Pro 125 Maxi Scooter", "scooter", "ScootyBazaar",
             125000, 134000,
             "Premium 125cc maxi-scooter with a bold muscular design. Disc brakes on both wheels, "
             "combi-braking system (CBS), LED DRL, and a large 2-person seat with backrest. "
             "Ideal for long rides and highway commutes.",
             None, 8, 4.5),

            # ---------- Accessories ----------
            ("ISI-Certified Full-Face Helmet (Matte Black)", "accessory", "SafeHead",
             1999, 2499,
             "DOT & ISI certified full-face helmet with anti-fog visor, quick-release strap, "
             "and internal sun shield. Fits head sizes M / L / XL. Comfortable high-density foam padding, "
             "removable washable liner.",
             None, 50, 4.4),

            ("Waterproof Scooter Body Cover", "accessory", "ShieldPro",
             799, 1299,
             "Heavy-duty 190T polyester cover with reflective strips. Protects your scooter from sun, rain, "
             "dust, and bird droppings. Elasticated hem for snug fit. Fits most 100cc–150cc scooters.",
             None, 100, 4.2),

            ("Mobile Holder with USB Charger", "accessory", "GripX",
             649, 999,
             "360° rotatable aluminium mobile mount that clamps to the handlebar. Built-in 5V/2A USB-A charging "
             "port, wired directly to the scooter battery. Fits phones 4.5\"–7.2\".",
             None, 75, 4.3),

            ("Leg Guard with Foot-Rest (Chrome)", "accessory", "ChromeCraft",
             1499, 1899,
             "Heavy-duty chrome-plated steel leg guard. Protects your legs in side-falls and adds extra "
             "foot-rest space for a passenger. Bolt-on installation, fits most Indian scooter models.",
             None, 40, 4.0),

            ("LED Fog Light Kit (Pair)", "accessory", "BrightRide",
             1299, 1799,
             "Pair of 30W LED auxiliary fog lights with universal mounting bracket and waterproof wiring harness. "
             "6500K bright-white beam, aluminium housing for heat dissipation. Includes handlebar on/off switch.",
             None, 60, 4.2),
        ]
        cur.executemany(
            """INSERT INTO products
               (name, category, brand, price, old_price, description, image, stock, rating, vendor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 2)""",
            sample,
        )
        conn.commit()

        # Seed product_images table.
        # The Thunder Bolt X1 (product id=1) gets 4 demo images.
        # Other products with a single image get that one registered too.
        image_seed = {
            1: ["scooter_red.png", "scooter_red_2.png",
                "scooter_red_3.png", "scooter_red_4.png"],
        }
        for pid, filenames in image_seed.items():
            for idx, fn in enumerate(filenames):
                cur.execute(
                    "INSERT INTO product_images (product_id, filename, sort_order) VALUES (?, ?, ?)",
                    (pid, fn, idx),
                )
        conn.commit()

    conn.close()


# ----------------------------- HELPERS --------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access only.", "danger")
            return redirect(url_for("portal"))
        return view(*args, **kwargs)
    return wrapper


def vendor_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("vendor", "admin"):
            flash("Vendor access only.", "danger")
            return redirect(url_for("vendor_login"))
        return view(*args, **kwargs)
    return wrapper


def normalize_phone(raw):
    """Strip all non-digits. If 10 digits, prepend '91' (India). Return digits-only string."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def whatsapp_link(product):
    """Build a wa.me link pre-filled with the order message."""
    msg = (f"Hi ScootyBazaar! I want to buy:\n\n"
           f"*{product['name']}*\n"
           f"Price: ₹{int(product['price']):,}\n"
           f"Product ID: #{product['id']}\n\n"
           f"Please share the next steps.")
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(msg)}"


@app.context_processor
def inject_globals():
    """Make these variables available in every template."""
    return {
        "current_user": session.get("username"),
        "role": session.get("role"),
        "is_admin": session.get("role") == "admin",
        "is_vendor": session.get("role") == "vendor",
        "whatsapp_number": WHATSAPP_NUMBER,
        "current_year": datetime.now().year,
    }


# ----------------------------- PUBLIC ROUTES --------------------------------
@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    sql = """SELECT p.*, u.business_name AS vendor_name
             FROM products p LEFT JOIN users u ON p.vendor_id = u.id
             WHERE 1=1"""
    params = []
    if q:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.brand LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]
    if category in ("scooter", "accessory"):
        sql += " AND p.category = ?"
        params.append(category)
    sql += " ORDER BY p.created_at DESC"

    products = db.execute(sql, params).fetchall()
    scooters = [p for p in products if p["category"] == "scooter"]
    accessories = [p for p in products if p["category"] == "accessory"]

    return render_template("index.html",
                           scooters=scooters,
                           accessories=accessories,
                           q=q, category=category)


@app.route("/product/<int:pid>")
def product_detail(pid):
    db = get_db()
    product = db.execute(
        """SELECT p.*, u.business_name AS vendor_name, u.id AS v_id
           FROM products p LEFT JOIN users u ON p.vendor_id = u.id
           WHERE p.id = ?""", (pid,)
    ).fetchone()
    if not product:
        abort(404)

    # Fetch all gallery images for this product
    images = db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY sort_order, id",
        (pid,),
    ).fetchall()

    related = db.execute(
        "SELECT * FROM products WHERE category = ? AND id != ? LIMIT 4",
        (product["category"], pid),
    ).fetchall()

    return render_template("product_detail.html",
                           product=product,
                           images=images,
                           wa_link=whatsapp_link(product),
                           related=related)


@app.route("/buy/<int:pid>")
def buy_now(pid):
    """Customers must be logged in to buy — then redirect to WhatsApp."""
    if "user_id" not in session:
        flash("Please login to place an order.", "warning")
        return redirect(url_for("login", next=url_for("product_detail", pid=pid)))

    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)
    if product["stock"] <= 0:
        flash("Sorry, this product is out of stock.", "danger")
        return redirect(url_for("product_detail", pid=pid))

    return redirect(whatsapp_link(product))


# ----------------------------- CUSTOMER AUTH --------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip().lower()
        phone    = request.form.get("phone", "").strip()
        password = request.form["password"]
        confirm  = request.form["confirm"]

        if not username or not email or not password:
            flash("All starred fields are required.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        else:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, email, password, phone) VALUES (?, ?, ?, ?)",
                    (username, email, generate_password_hash(password), phone),
                )
                db.commit()
                flash("Account created! Please login.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Username or email already exists.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        password   = request.form["password"]
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE (username = ? OR email = ?) AND role = 'customer'",
            (identifier, identifier.lower()),
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid credentials.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("index"))


# ----------------------------- VENDOR AUTH ----------------------------------
@app.route("/vendor/register", methods=["GET", "POST"])
def vendor_register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip().lower()
        phone    = normalize_phone(request.form.get("phone", ""))
        business_name    = request.form.get("business_name", "").strip()
        business_address = request.form.get("business_address", "").strip()
        password = request.form["password"]
        confirm  = request.form["confirm"]

        if not username or not email or not password or not business_name or not phone:
            flash("All starred fields are required.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif len(phone) != 12:
            flash("Please enter a valid 10-digit mobile number.", "danger")
        else:
            db = get_db()
            try:
                db.execute(
                    """INSERT INTO users
                       (username, email, password, phone, role, business_name, business_address)
                       VALUES (?, ?, ?, ?, 'vendor', ?, ?)""",
                    (username, email, generate_password_hash(password),
                     phone, business_name, business_address),
                )
                db.commit()
                flash("Vendor account created! Please login to start listing products.", "success")
                return redirect(url_for("vendor_login"))
            except sqlite3.IntegrityError:
                flash("Username or email already exists.", "danger")

    return render_template("vendor_register.html")


@app.route("/vendor/login", methods=["GET", "POST"])
def vendor_login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        password   = request.form["password"]
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE (username = ? OR email = ?) AND role = 'vendor'",
            (identifier, identifier.lower()),
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            flash(f"Welcome, {user['business_name'] or user['username']}!", "success")
            return redirect(url_for("vendor_dashboard"))
        flash("Invalid vendor credentials.", "danger")

    return render_template("vendor_login.html")


@app.route("/vendor")
@vendor_required
def vendor_dashboard():
    db = get_db()
    uid = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    products = db.execute(
        "SELECT * FROM products WHERE vendor_id = ? ORDER BY id DESC", (uid,)
    ).fetchall()
    stats = {
        "total":       len(products),
        "scooters":    sum(1 for p in products if p["category"] == "scooter"),
        "accessories": sum(1 for p in products if p["category"] == "accessory"),
        "in_stock":    sum(1 for p in products if p["stock"] > 0),
    }
    return render_template("vendor_dashboard.html",
                           products=products, stats=stats, vendor=user)


@app.route("/vendor/product/new", methods=["GET", "POST"])
@vendor_required
def vendor_new_product():
    if request.method == "POST":
        data = _collect_product_form()
        if data is None:
            return render_template("product_form.html",
                                   product=None, images=[], mode="vendor")
        uploaded = data.pop("_uploaded_files")
        db = get_db()
        cur = db.execute(
            """INSERT INTO products (name, category, brand, price, old_price,
                                     description, image, stock, rating, vendor_id)
               VALUES (:name, :category, :brand, :price, :old_price,
                       :description, :image, :stock, :rating, :vendor_id)""",
            {**data, "vendor_id": session["user_id"]},
        )
        new_pid = cur.lastrowid
        for idx, fn in enumerate(uploaded):
            db.execute("INSERT INTO product_images (product_id, filename, sort_order) VALUES (?, ?, ?)",
                       (new_pid, fn, idx))
        if uploaded and not data.get("image"):
            db.execute("UPDATE products SET image=? WHERE id=?", (uploaded[0], new_pid))
        db.commit()
        flash(f"Product added with {len(uploaded)} image(s).", "success")
        return redirect(url_for("vendor_dashboard"))

    return render_template("product_form.html", product=None, images=[], mode="vendor")


@app.route("/vendor/product/<int:pid>/edit", methods=["GET", "POST"])
@vendor_required
def vendor_edit_product(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)
    # Vendors can only edit their own products (admins can edit any via /admin route)
    if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
        abort(403)

    images = db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY sort_order, id",
        (pid,),
    ).fetchall()

    if request.method == "POST":
        data = _collect_product_form(existing_image=product["image"])
        if data is None:
            return render_template("product_form.html",
                                   product=product, images=images, mode="vendor")
        uploaded = data.pop("_uploaded_files")
        data["id"] = pid
        db.execute(
            """UPDATE products SET
                 name=:name, category=:category, brand=:brand,
                 price=:price, old_price=:old_price,
                 description=:description, image=:image,
                 stock=:stock, rating=:rating
               WHERE id=:id""",
            data,
        )
        if uploaded:
            row = db.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM product_images WHERE product_id=?", (pid,)
            ).fetchone()
            next_order = row[0] + 1
            for fn in uploaded:
                db.execute("INSERT INTO product_images (product_id, filename, sort_order) VALUES (?, ?, ?)",
                           (pid, fn, next_order))
                next_order += 1
            if not product["image"]:
                db.execute("UPDATE products SET image=? WHERE id=?", (uploaded[0], pid))
        db.commit()
        flash(f"Product updated. {len(uploaded)} new image(s) added." if uploaded else "Product updated.", "success")
        return redirect(url_for("vendor_edit_product", pid=pid))

    return render_template("product_form.html", product=product, images=images, mode="vendor")


@app.route("/vendor/product/<int:pid>/delete", methods=["POST"])
@vendor_required
def vendor_delete_product(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)
    if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
        abort(403)
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    flash("Product deleted.", "info")
    return redirect(url_for("vendor_dashboard"))


@app.route("/vendor/product/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@vendor_required
def vendor_delete_image(pid, img_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)
    if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
        abort(403)
    img = db.execute("SELECT * FROM product_images WHERE id = ? AND product_id = ?",
                     (img_id, pid)).fetchone()
    if not img:
        abort(404)
    db.execute("DELETE FROM product_images WHERE id = ?", (img_id,))
    if product["image"] == img["filename"]:
        replacement = db.execute(
            "SELECT filename FROM product_images WHERE product_id = ? ORDER BY sort_order, id LIMIT 1",
            (pid,),
        ).fetchone()
        db.execute("UPDATE products SET image = ? WHERE id = ?",
                   (replacement["filename"] if replacement else None, pid))
    db.commit()
    flash("Image deleted.", "info")
    return redirect(url_for("vendor_edit_product", pid=pid))


# ----------------------------- HIDDEN ADMIN PORTAL (OTP) --------------------
# This URL is NOT linked anywhere on the public site.
# To access: visit ADMIN_PORTAL_PATH and enter the admin's registered email.
@app.route(ADMIN_PORTAL_PATH, methods=["GET", "POST"])
def portal():
    """Hidden admin login via username + password."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND role = 'admin'", (username,)
        ).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = "admin"
            flash("Admin access granted.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "danger")

    return render_template("portal.html")


@app.route("/admin/change-password", methods=["GET", "POST"])
@admin_required
def admin_change_password():
    """Let an authenticated admin change their password."""
    if request.method == "POST":
        current = request.form.get("current", "")
        new     = request.form.get("new", "")
        confirm = request.form.get("confirm", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()

        if not user or not check_password_hash(user["password"], current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new != confirm:
            flash("New passwords do not match.", "danger")
        elif new == current:
            flash("New password must be different from the current one.", "warning")
        else:
            db.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (generate_password_hash(new), session["user_id"]),
            )
            db.commit()
            flash("✅ Password changed successfully. Please login again with the new password.", "success")
            session.clear()
            return redirect(url_for("portal"))

    return render_template("admin_change_password.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    products = db.execute(
        """SELECT p.*, u.business_name AS vendor_name, u.username AS vendor_username
           FROM products p LEFT JOIN users u ON p.vendor_id = u.id
           ORDER BY p.id DESC"""
    ).fetchall()
    stats = {
        "total_products": len(products),
        "scooters":       sum(1 for p in products if p["category"] == "scooter"),
        "accessories":    sum(1 for p in products if p["category"] == "accessory"),
        "customers":      db.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
        "vendors":        db.execute("SELECT COUNT(*) FROM users WHERE role='vendor'").fetchone()[0],
    }
    return render_template("admin_dashboard.html", products=products, stats=stats)


@app.route("/admin/product/new", methods=["GET", "POST"])
@admin_required
def admin_new_product():
    if request.method == "POST":
        data = _collect_product_form()
        if data is None:
            return render_template("product_form.html", product=None, images=[], mode="admin")
        uploaded = data.pop("_uploaded_files")

        db = get_db()
        cur = db.execute(
            """INSERT INTO products (name, category, brand, price, old_price,
                                     description, image, stock, rating, vendor_id)
               VALUES (:name, :category, :brand, :price, :old_price,
                       :description, :image, :stock, :rating, :vendor_id)""",
            {**data, "vendor_id": session["user_id"]},
        )
        new_pid = cur.lastrowid

        for idx, fn in enumerate(uploaded):
            db.execute(
                "INSERT INTO product_images (product_id, filename, sort_order) VALUES (?, ?, ?)",
                (new_pid, fn, idx),
            )
        if uploaded and not data.get("image"):
            db.execute("UPDATE products SET image=? WHERE id=?", (uploaded[0], new_pid))
        db.commit()

        flash(f"Product added with {len(uploaded)} image(s).", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("product_form.html", product=None, images=[], mode="admin")


@app.route("/admin/product/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)

    images = db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY sort_order, id",
        (pid,),
    ).fetchall()

    if request.method == "POST":
        data = _collect_product_form(existing_image=product["image"])
        if data is None:
            return render_template("product_form.html", product=product, images=images, mode="admin")
        uploaded = data.pop("_uploaded_files")
        data["id"] = pid

        db.execute(
            """UPDATE products SET
                 name=:name, category=:category, brand=:brand,
                 price=:price, old_price=:old_price,
                 description=:description, image=:image,
                 stock=:stock, rating=:rating
               WHERE id=:id""",
            data,
        )

        if uploaded:
            row = db.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM product_images WHERE product_id=?",
                (pid,),
            ).fetchone()
            next_order = row[0] + 1
            for fn in uploaded:
                db.execute(
                    "INSERT INTO product_images (product_id, filename, sort_order) VALUES (?, ?, ?)",
                    (pid, fn, next_order),
                )
                next_order += 1

            if not product["image"]:
                db.execute("UPDATE products SET image=? WHERE id=?", (uploaded[0], pid))

        db.commit()
        flash(f"Product updated. {len(uploaded)} new image(s) added." if uploaded else "Product updated.", "success")
        return redirect(url_for("admin_edit_product", pid=pid))

    return render_template("product_form.html", product=product, images=images, mode="admin")


@app.route("/admin/product/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@admin_required
def admin_delete_image(pid, img_id):
    db = get_db()
    img = db.execute(
        "SELECT * FROM product_images WHERE id = ? AND product_id = ?",
        (img_id, pid),
    ).fetchone()
    if not img:
        abort(404)

    db.execute("DELETE FROM product_images WHERE id = ?", (img_id,))

    # If this was the product's primary image, pick a new primary (or clear it)
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if product and product["image"] == img["filename"]:
        replacement = db.execute(
            "SELECT filename FROM product_images WHERE product_id = ? ORDER BY sort_order, id LIMIT 1",
            (pid,),
        ).fetchone()
        db.execute(
            "UPDATE products SET image = ? WHERE id = ?",
            (replacement["filename"] if replacement else None, pid),
        )

    db.commit()
    flash("Image deleted.", "info")
    return redirect(url_for("admin_edit_product", pid=pid))


@app.route("/admin/product/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_delete_product(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    flash("Product deleted.", "info")
    return redirect(url_for("admin_dashboard"))


def _collect_product_form(existing_image=None):
    """Validate & normalise the product form.
    Returns dict (with special key '_uploaded_files' = list of saved filenames)
    or None on error."""
    try:
        name        = request.form["name"].strip()
        category    = request.form["category"].strip()
        brand       = request.form.get("brand", "").strip()
        price       = float(request.form["price"])
        old_price   = request.form.get("old_price", "").strip()
        old_price   = float(old_price) if old_price else None
        description = request.form.get("description", "").strip()
        stock       = int(request.form.get("stock", 0))
        rating      = float(request.form.get("rating", 4.0))
    except (ValueError, KeyError):
        flash("Please fill all fields with valid values.", "danger")
        return None

    if not name or category not in ("scooter", "accessory") or price <= 0:
        flash("Name, category and a positive price are required.", "danger")
        return None

    # Handle MULTIPLE image uploads (optional, up to 5)
    uploaded_filenames = []
    files = request.files.getlist("images")
    for file in files[:5]:  # cap at 5 images per upload
        if file and file.filename:
            if not allowed_file(file.filename):
                flash(f"'{file.filename}' — image must be png/jpg/jpeg/webp/gif.", "danger")
                return None
            safe = secure_filename(file.filename)
            safe = f"{int(datetime.now().timestamp() * 1000)}_{safe}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe))
            uploaded_filenames.append(safe)

    # `image` field = primary thumbnail filename.
    # Keep existing one unless the admin uploaded new images AND there was none before.
    primary_image = existing_image
    if uploaded_filenames and not primary_image:
        primary_image = uploaded_filenames[0]

    return {
        "name": name, "category": category, "brand": brand,
        "price": price, "old_price": old_price,
        "description": description, "image": primary_image,
        "stock": stock, "rating": rating,
        "_uploaded_files": uploaded_filenames,
    }


# ----------------------------- ERRORS ---------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ----------------------------- MAIN -----------------------------------------
# Initialize DB when the module loads (so gunicorn / production servers also run it)
init_db()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ScootyBazaar is running!")
    print("  Open: http://127.0.0.1:5000")
    print("")
    print(f"  Vendor login:    http://127.0.0.1:5000/vendor/login")
    print(f"     demo user: scootybazaar  /  vendor123")
    print("")
    print(f"  Admin portal (HIDDEN): http://127.0.0.1:5000{ADMIN_PORTAL_PATH}")
    print(f"     Default username: {DEFAULT_ADMIN_USERNAME}")
    print(f"     Default password: {DEFAULT_ADMIN_PASSWORD}")
    print(f"     ⚠️  Change this password after first login!")
    print("=" * 60 + "\n")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
