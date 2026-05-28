"""
ScootyBazaar - Flask + Postgres (Supabase) + AWS S3.

Storage:
- Database:  Postgres via DATABASE_URL env var (Supabase Transaction pooler).
- Images:    AWS S3 if AWS_S3_BUCKET set, else local /static/images/.
- Old seed images bundled in the repo continue to work in either mode.
"""

import os
from urllib.parse import quote, urlparse
from functools import wraps
from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ----------------------------- CONFIG ---------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

WHATSAPP_NUMBER = "918789899421"
ADMIN_PORTAL_PATH = "/portal"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "nirmal123456"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-in-production-please")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


# ============================ DATABASE (POSTGRES) ===========================
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Track DB status so the app can still boot (and show errors) when DB is misconfigured.
_db_pool = None
_db_error = None

if not DATABASE_URL:
    _db_error = (
        "DATABASE_URL env var is not set. Set it in Render's Environment tab "
        "(use Supabase Transaction pooler URI on port 6543)."
    )
    print(f"[DB] FATAL CONFIG ERROR: {_db_error}")
else:
    # Mask password before logging the URL — helps debug typos without leaking secrets.
    try:
        from urllib.parse import urlparse as _urlparse
        _u = _urlparse(DATABASE_URL)
        _masked_host = _u.hostname or "?"
        _masked_port = _u.port or "?"
        _masked_user = _u.username or "?"
        _masked_db   = (_u.path or "/?").lstrip("/")
        print(f"[DB] Attempting connection: user={_masked_user} host={_masked_host} port={_masked_port} db={_masked_db}")
    except Exception as _e:
        print(f"[DB] Could not parse DATABASE_URL: {_e}")

    try:
        _db_pool = pg_pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
        )
        # Test the connection right away so failures show up at boot, not first request.
        _test_conn = _db_pool.getconn()
        with _test_conn.cursor() as _c:
            _c.execute("SELECT 1")
        _db_pool.putconn(_test_conn)
        print(f"[DB] Connected to Postgres via pool (max 5 connections).")
    except Exception as e:
        _db_error = f"{type(e).__name__}: {e}"
        print(f"[DB] FATAL CONNECTION ERROR: {_db_error}")
        print(f"[DB] Common causes:")
        print(f"[DB]   1. Special characters in password (use only letters/numbers)")
        print(f"[DB]   2. Wrong password — reset it in Supabase Settings → Database")
        print(f"[DB]   3. Wrong port — must be 6543 (Transaction pooler), not 5432")
        print(f"[DB]   4. Supabase project paused — restore it in the Supabase dashboard")
        _db_pool = None


def get_db():
    """Borrow a connection from the pool for the duration of one request."""
    if _db_pool is None:
        raise RuntimeError(f"Database is not configured: {_db_error}")
    if "db" not in g:
        g.db = _db_pool.getconn()
    return g.db


def get_cursor():
    """Convenience: dict-style cursor so rows act like SQLite Row objects."""
    return get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None and _db_pool is not None:
        # Roll back any open transaction on error, otherwise commit
        try:
            if error is None:
                db.commit()
            else:
                db.rollback()
        except Exception:
            pass
        _db_pool.putconn(db)


def init_db():
    """Create tables & seed initial data if the DB is empty.
    Idempotent - safe to call on every startup."""
    if _db_pool is None:
        print("[DB] Skipping init_db (no DB connection).")
        return
    conn = _db_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Tables ----------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id               SERIAL PRIMARY KEY,
                    username         TEXT UNIQUE NOT NULL,
                    email            TEXT UNIQUE NOT NULL,
                    password         TEXT NOT NULL,
                    phone            TEXT,
                    role             TEXT DEFAULT 'customer',
                    business_name    TEXT,
                    business_address TEXT,
                    approved         INTEGER DEFAULT 1,
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    category    TEXT NOT NULL,
                    brand       TEXT,
                    price       REAL NOT NULL,
                    old_price   REAL,
                    description TEXT,
                    image       TEXT,
                    stock       INTEGER DEFAULT 10,
                    rating      REAL DEFAULT 4.2,
                    vendor_id   INTEGER DEFAULT 1,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vendor_id) REFERENCES users(id) ON DELETE SET NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS product_images (
                    id          SERIAL PRIMARY KEY,
                    product_id  INTEGER NOT NULL,
                    filename    TEXT NOT NULL,
                    sort_order  INTEGER DEFAULT 0,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                );
            """)

            # Seed admin + sample vendor on first run ------------------------
            cur.execute("SELECT COUNT(*) FROM users")
            user_count = cur.fetchone()[0]
            if user_count == 0:
                cur.execute(
                    "INSERT INTO users (username, email, password, phone, role, business_name) "
                    "VALUES (%s, %s, %s, %s, 'admin', %s) ON CONFLICT (username) DO NOTHING",
                    (DEFAULT_ADMIN_USERNAME, "admin@scootybazaar.com",
                     generate_password_hash(DEFAULT_ADMIN_PASSWORD), WHATSAPP_NUMBER, "ScootyBazaar HQ"),
                )
                cur.execute(
                    "INSERT INTO users (username, email, password, phone, role, business_name, business_address) "
                    "VALUES (%s, %s, %s, %s, 'vendor', %s, %s) ON CONFLICT (username) DO NOTHING",
                    ("scootybazaar", "seller@scootybazaar.com",
                     generate_password_hash("vendor123"), "919999999999",
                     "ScootyBazaar Authorised Seller", "MG Road, New Delhi - 110001"),
                )

            # Seed sample products on first run ------------------------------
            cur.execute("SELECT COUNT(*) FROM products")
            product_count = cur.fetchone()[0]
            if product_count == 0:
                sample = [
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
                     "removable battery that you can charge indoors. Speeds up to 45 km/h - no license required "
                     "(as per Indian EV norms for low-speed vehicles). Available in 4 colours.",
                     None, 30, 4.1),
                    ("RoadMaster Pro 125 Maxi Scooter", "scooter", "ScootyBazaar",
                     125000, 134000,
                     "Premium 125cc maxi-scooter with a bold muscular design. Disc brakes on both wheels, "
                     "combi-braking system (CBS), LED DRL, and a large 2-person seat with backrest. "
                     "Ideal for long rides and highway commutes.",
                     None, 8, 4.5),
                    ("ISI-Certified Full-Face Helmet (Matte Black)", "accessory", "SafeHead",
                     1999, 2499,
                     "DOT & ISI certified full-face helmet with anti-fog visor, quick-release strap, "
                     "and internal sun shield. Fits head sizes M / L / XL. Comfortable high-density foam padding, "
                     "removable washable liner.",
                     None, 50, 4.4),
                    ("Waterproof Scooter Body Cover", "accessory", "ShieldPro",
                     799, 1299,
                     "Heavy-duty 190T polyester cover with reflective strips. Protects your scooter from sun, rain, "
                     "dust, and bird droppings. Elasticated hem for snug fit. Fits most 100cc-150cc scooters.",
                     None, 100, 4.2),
                    ("Mobile Holder with USB Charger", "accessory", "GripX",
                     649, 999,
                     "360-degree rotatable aluminium mobile mount that clamps to the handlebar. Built-in 5V/2A USB-A "
                     "charging port, wired directly to the scooter battery. Fits phones 4.5\"-7.2\".",
                     None, 75, 4.3),
                    ("Leg Guard with Foot-Rest (Chrome)", "accessory", "ChromeCraft",
                     1499, 1899,
                     "Heavy-duty chrome-plated steel leg guard. Protects your legs in side-falls and adds extra "
                     "footrest space for long rides. Universal-fit, comes with all mounting hardware.",
                     None, 40, 4.0),
                ]
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO products (name, category, brand, price, old_price, description, image, stock, rating) VALUES %s",
                    sample,
                )

                gallery = [
                    (1, "scooter_red.png", 0),
                    (1, "scooter_red_side.png", 1),
                    (1, "scooter_red_dash.png", 2),
                    (1, "scooter_red_detail.png", 3),
                ]
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO product_images (product_id, filename, sort_order) VALUES %s",
                    gallery,
                )

            conn.commit()
            print("[DB] Schema ready (created tables if missing, seeded if empty).")
    finally:
        _db_pool.putconn(conn)


# ============================ S3 STORAGE LAYER ==============================
S3_BUCKET     = os.environ.get("AWS_S3_BUCKET", "").strip()
S3_REGION     = os.environ.get("AWS_S3_REGION", "ap-south-1").strip()
S3_PUBLIC_URL = os.environ.get("AWS_S3_PUBLIC_URL", "").strip().rstrip("/")
USE_S3        = bool(S3_BUCKET)

s3_client = None
if USE_S3:
    try:
        import boto3
        s3_client = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        print(f"[S3] Enabled - bucket={S3_BUCKET} region={S3_REGION}")
    except ImportError:
        print("[S3] boto3 not installed; falling back to local storage.")
        USE_S3 = False
    except Exception as e:
        print(f"[S3] Failed to initialise client: {e}; falling back to local storage.")
        USE_S3 = False
else:
    print("[S3] AWS_S3_BUCKET not set - using local /static/images/ storage.")


def _s3_public_url(key: str) -> str:
    if S3_PUBLIC_URL:
        return f"{S3_PUBLIC_URL}/{key}"
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}"


def upload_to_s3(file_storage, filename: str):
    key = f"products/{filename}"
    extra = {}
    if file_storage.content_type:
        extra["ContentType"] = file_storage.content_type
    extra["CacheControl"] = "public, max-age=31536000, immutable"
    try:
        file_storage.stream.seek(0)
        s3_client.upload_fileobj(file_storage.stream, S3_BUCKET, key, ExtraArgs=extra)
        return _s3_public_url(key)
    except Exception as e:
        print(f"[S3] Upload failed for {filename}: {e}")
        return None


def delete_from_s3(url_or_filename: str) -> None:
    if not USE_S3 or not url_or_filename:
        return
    if not url_or_filename.startswith(("http://", "https://")):
        return
    try:
        if S3_PUBLIC_URL and url_or_filename.startswith(S3_PUBLIC_URL):
            key = url_or_filename[len(S3_PUBLIC_URL):].lstrip("/")
        else:
            key = urlparse(url_or_filename).path.lstrip("/")
        if key:
            s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
    except Exception as e:
        print(f"[S3] Delete failed for {url_or_filename}: {e}")


def image_url(filename_or_url: str) -> str:
    if not filename_or_url:
        return ""
    if filename_or_url.startswith(("http://", "https://")):
        return filename_or_url
    return url_for("static", filename="images/" + filename_or_url)


@app.context_processor
def inject_helpers():
    return dict(image_url=image_url, whatsapp_number=WHATSAPP_NUMBER)


# ----------------------------- HELPERS --------------------------------------
def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def normalize_phone(phone):
    if not phone:
        return ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


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
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def vendor_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("vendor", "admin"):
            flash("Vendor login required.", "warning")
            return redirect(url_for("vendor_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


# ----------------------------- PUBLIC ROUTES --------------------------------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    sql = """SELECT p.*, u.business_name AS vendor_name
             FROM products p LEFT JOIN users u ON p.vendor_id = u.id"""
    params = []
    where = []
    if q:
        where.append("(p.name ILIKE %s OR p.description ILIKE %s OR p.brand ILIKE %s)")
        like = f"%{q}%"
        params += [like, like, like]
    if category in ("scooter", "accessory"):
        where.append("p.category = %s")
        params.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.id DESC"

    with get_cursor() as cur:
        cur.execute(sql, params)
        products = cur.fetchall()

    scooters = [p for p in products if p["category"] == "scooter"]
    accessories = [p for p in products if p["category"] == "accessory"]
    return render_template("index.html",
                           products=products, scooters=scooters,
                           accessories=accessories, q=q, category=category)


@app.route("/product/<int:pid>")
def product_detail(pid):
    with get_cursor() as cur:
        cur.execute(
            """SELECT p.*, u.business_name AS vendor_name, u.phone AS vendor_phone
               FROM products p LEFT JOIN users u ON p.vendor_id = u.id
               WHERE p.id = %s""", (pid,),
        )
        product = cur.fetchone()
        if not product:
            abort(404)

        cur.execute(
            "SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order, id",
            (pid,),
        )
        images = cur.fetchall()

        cur.execute(
            "SELECT * FROM products WHERE category = %s AND id != %s ORDER BY RANDOM() LIMIT 4",
            (product["category"], pid),
        )
        related = cur.fetchall()

    return render_template(
        "product_detail.html",
        product=product, images=images, related=related,
        whatsapp_number=product["vendor_phone"] or WHATSAPP_NUMBER,
    )


@app.route("/buy/<int:pid>")
def buy_now(pid):
    with get_cursor() as cur:
        cur.execute(
            """SELECT p.*, u.phone AS vendor_phone
               FROM products p LEFT JOIN users u ON p.vendor_id = u.id
               WHERE p.id = %s""", (pid,),
        )
        product = cur.fetchone()
    if not product:
        abort(404)
    msg = (
        f"Hi! I'm interested in *{product['name']}* "
        f"(Rs.{int(product['price']):,}) from ScootyBazaar. "
        f"Please share availability and delivery details."
    )
    number = product["vendor_phone"] or WHATSAPP_NUMBER
    return redirect(f"https://wa.me/{number}?text={quote(msg)}")


# ----------------------------- CUSTOMER AUTH --------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip().lower()
        phone    = normalize_phone(request.form.get("phone", ""))
        password = request.form["password"]
        confirm  = request.form["confirm"]

        if not username or not email or not password:
            flash("All fields are required.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        else:
            try:
                with get_cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (username, email, password, phone, role) "
                        "VALUES (%s, %s, %s, %s, 'customer')",
                        (username, email, generate_password_hash(password), phone),
                    )
                flash("Account created. Please login.", "success")
                return redirect(url_for("login"))
            except psycopg2.IntegrityError:
                get_db().rollback()
                flash("Username or email already exists.", "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        password   = request.form["password"]
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE (username = %s OR email = %s) AND role = 'customer'",
                (identifier, identifier.lower()),
            )
            user = cur.fetchone()

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
            try:
                with get_cursor() as cur:
                    cur.execute(
                        """INSERT INTO users
                           (username, email, password, phone, role, business_name, business_address)
                           VALUES (%s, %s, %s, %s, 'vendor', %s, %s)""",
                        (username, email, generate_password_hash(password),
                         phone, business_name, business_address),
                    )
                flash("Vendor account created! Please login to start listing products.", "success")
                return redirect(url_for("vendor_login"))
            except psycopg2.IntegrityError:
                get_db().rollback()
                flash("Username or email already exists.", "danger")

    return render_template("vendor_register.html")


@app.route("/vendor/login", methods=["GET", "POST"])
def vendor_login():
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        password   = request.form["password"]
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE (username = %s OR email = %s) AND role = 'vendor'",
                (identifier, identifier.lower()),
            )
            user = cur.fetchone()

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
    uid = session["user_id"]
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (uid,))
        user = cur.fetchone()
        cur.execute(
            "SELECT * FROM products WHERE vendor_id = %s ORDER BY id DESC", (uid,)
        )
        products = cur.fetchall()
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
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO products (name, category, brand, price, old_price,
                                         description, image, stock, rating, vendor_id)
                   VALUES (%(name)s, %(category)s, %(brand)s, %(price)s, %(old_price)s,
                           %(description)s, %(image)s, %(stock)s, %(rating)s, %(vendor_id)s)
                   RETURNING id""",
                {**data, "vendor_id": session["user_id"]},
            )
            new_pid = cur.fetchone()["id"]
            for idx, fn in enumerate(uploaded):
                cur.execute(
                    "INSERT INTO product_images (product_id, filename, sort_order) VALUES (%s, %s, %s)",
                    (new_pid, fn, idx),
                )
            if uploaded and not data.get("image"):
                cur.execute("UPDATE products SET image=%s WHERE id=%s", (uploaded[0], new_pid))
        flash(f"Product added with {len(uploaded)} image(s).", "success")
        return redirect(url_for("vendor_dashboard"))

    return render_template("product_form.html", product=None, images=[], mode="vendor")


@app.route("/vendor/product/<int:pid>/edit", methods=["GET", "POST"])
@vendor_required
def vendor_edit_product(pid):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        product = cur.fetchone()
    if not product:
        abort(404)
    if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
        abort(403)

    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order, id",
            (pid,),
        )
        images = cur.fetchall()

    if request.method == "POST":
        data = _collect_product_form(existing_image=product["image"])
        if data is None:
            return render_template("product_form.html",
                                   product=product, images=images, mode="vendor")
        uploaded = data.pop("_uploaded_files")
        data["id"] = pid
        with get_cursor() as cur:
            cur.execute(
                """UPDATE products SET
                     name=%(name)s, category=%(category)s, brand=%(brand)s,
                     price=%(price)s, old_price=%(old_price)s,
                     description=%(description)s, image=%(image)s,
                     stock=%(stock)s, rating=%(rating)s
                   WHERE id=%(id)s""",
                data,
            )
            if uploaded:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) AS m FROM product_images WHERE product_id=%s",
                    (pid,),
                )
                next_order = cur.fetchone()["m"] + 1
                for fn in uploaded:
                    cur.execute(
                        "INSERT INTO product_images (product_id, filename, sort_order) VALUES (%s, %s, %s)",
                        (pid, fn, next_order),
                    )
                    next_order += 1
                if not product["image"]:
                    cur.execute("UPDATE products SET image=%s WHERE id=%s", (uploaded[0], pid))
        flash(f"Product updated. {len(uploaded)} new image(s) added." if uploaded else "Product updated.", "success")
        return redirect(url_for("vendor_edit_product", pid=pid))

    return render_template("product_form.html", product=product, images=images, mode="vendor")


@app.route("/vendor/product/<int:pid>/delete", methods=["POST"])
@vendor_required
def vendor_delete_product(pid):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        product = cur.fetchone()
        if not product:
            abort(404)
        if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
            abort(403)

        cur.execute("SELECT filename FROM product_images WHERE product_id = %s", (pid,))
        imgs = cur.fetchall()
        for img in imgs:
            delete_from_s3(img["filename"])

        cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    flash("Product deleted.", "info")
    return redirect(url_for("vendor_dashboard"))


@app.route("/vendor/product/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@vendor_required
def vendor_delete_image(pid, img_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        product = cur.fetchone()
        if not product:
            abort(404)
        if product["vendor_id"] != session["user_id"] and session.get("role") != "admin":
            abort(403)
        cur.execute(
            "SELECT * FROM product_images WHERE id = %s AND product_id = %s",
            (img_id, pid),
        )
        img = cur.fetchone()
        if not img:
            abort(404)

        delete_from_s3(img["filename"])
        cur.execute("DELETE FROM product_images WHERE id = %s", (img_id,))

        if product["image"] == img["filename"]:
            cur.execute(
                "SELECT filename FROM product_images WHERE product_id = %s ORDER BY sort_order, id LIMIT 1",
                (pid,),
            )
            replacement = cur.fetchone()
            cur.execute(
                "UPDATE products SET image = %s WHERE id = %s",
                (replacement["filename"] if replacement else None, pid),
            )
    flash("Image deleted.", "info")
    return redirect(url_for("vendor_edit_product", pid=pid))


# ----------------------------- HIDDEN ADMIN PORTAL --------------------------
@app.route(ADMIN_PORTAL_PATH, methods=["GET", "POST"])
def portal():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE username = %s AND role = 'admin'", (username,)
            )
            user = cur.fetchone()
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
    if request.method == "POST":
        current = request.form.get("current", "")
        new     = request.form.get("new", "")
        confirm = request.form.get("confirm", "")

        with get_cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
            user = cur.fetchone()

        if not user or not check_password_hash(user["password"], current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new != confirm:
            flash("New passwords do not match.", "danger")
        elif new == current:
            flash("New password must be different from the current one.", "warning")
        else:
            with get_cursor() as cur:
                cur.execute(
                    "UPDATE users SET password = %s WHERE id = %s",
                    (generate_password_hash(new), session["user_id"]),
                )
            flash("Password changed successfully. Please login again with the new password.", "success")
            session.clear()
            return redirect(url_for("portal"))

    return render_template("admin_change_password.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    with get_cursor() as cur:
        cur.execute(
            """SELECT p.*, u.business_name AS vendor_name, u.username AS vendor_username
               FROM products p LEFT JOIN users u ON p.vendor_id = u.id
               ORDER BY p.id DESC"""
        )
        products = cur.fetchall()
    stats = {
        "total":       len(products),
        "scooters":    sum(1 for p in products if p["category"] == "scooter"),
        "accessories": sum(1 for p in products if p["category"] == "accessory"),
        "in_stock":    sum(1 for p in products if p["stock"] > 0),
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
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO products (name, category, brand, price, old_price,
                                         description, image, stock, rating, vendor_id)
                   VALUES (%(name)s, %(category)s, %(brand)s, %(price)s, %(old_price)s,
                           %(description)s, %(image)s, %(stock)s, %(rating)s, %(vendor_id)s)
                   RETURNING id""",
                {**data, "vendor_id": session["user_id"]},
            )
            new_pid = cur.fetchone()["id"]
            for idx, fn in enumerate(uploaded):
                cur.execute(
                    "INSERT INTO product_images (product_id, filename, sort_order) VALUES (%s, %s, %s)",
                    (new_pid, fn, idx),
                )
            if uploaded and not data.get("image"):
                cur.execute("UPDATE products SET image=%s WHERE id=%s", (uploaded[0], new_pid))
        flash(f"Product added with {len(uploaded)} image(s).", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("product_form.html", product=None, images=[], mode="admin")


@app.route("/admin/product/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(pid):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        product = cur.fetchone()
    if not product:
        abort(404)

    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order, id",
            (pid,),
        )
        images = cur.fetchall()

    if request.method == "POST":
        data = _collect_product_form(existing_image=product["image"])
        if data is None:
            return render_template("product_form.html", product=product, images=images, mode="admin")
        uploaded = data.pop("_uploaded_files")
        data["id"] = pid

        with get_cursor() as cur:
            cur.execute(
                """UPDATE products SET
                     name=%(name)s, category=%(category)s, brand=%(brand)s,
                     price=%(price)s, old_price=%(old_price)s,
                     description=%(description)s, image=%(image)s,
                     stock=%(stock)s, rating=%(rating)s
                   WHERE id=%(id)s""",
                data,
            )
            if uploaded:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) AS m FROM product_images WHERE product_id=%s",
                    (pid,),
                )
                next_order = cur.fetchone()["m"] + 1
                for fn in uploaded:
                    cur.execute(
                        "INSERT INTO product_images (product_id, filename, sort_order) VALUES (%s, %s, %s)",
                        (pid, fn, next_order),
                    )
                    next_order += 1
                if not product["image"]:
                    cur.execute("UPDATE products SET image=%s WHERE id=%s", (uploaded[0], pid))
        flash(f"Product updated. {len(uploaded)} new image(s) added." if uploaded else "Product updated.", "success")
        return redirect(url_for("admin_edit_product", pid=pid))

    return render_template("product_form.html", product=product, images=images, mode="admin")


@app.route("/admin/product/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@admin_required
def admin_delete_image(pid, img_id):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM product_images WHERE id = %s AND product_id = %s",
            (img_id, pid),
        )
        img = cur.fetchone()
        if not img:
            abort(404)

        delete_from_s3(img["filename"])
        cur.execute("DELETE FROM product_images WHERE id = %s", (img_id,))

        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        product = cur.fetchone()
        if product and product["image"] == img["filename"]:
            cur.execute(
                "SELECT filename FROM product_images WHERE product_id = %s ORDER BY sort_order, id LIMIT 1",
                (pid,),
            )
            replacement = cur.fetchone()
            cur.execute(
                "UPDATE products SET image = %s WHERE id = %s",
                (replacement["filename"] if replacement else None, pid),
            )
    flash("Image deleted.", "info")
    return redirect(url_for("admin_edit_product", pid=pid))


@app.route("/admin/product/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_delete_product(pid):
    with get_cursor() as cur:
        cur.execute("SELECT filename FROM product_images WHERE product_id = %s", (pid,))
        imgs = cur.fetchall()
        for img in imgs:
            delete_from_s3(img["filename"])

        cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    flash("Product deleted.", "info")
    return redirect(url_for("admin_dashboard"))


def _collect_product_form(existing_image=None):
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

    uploaded_filenames = []
    files = request.files.getlist("images")
    for file in files[:5]:
        if file and file.filename:
            if not allowed_file(file.filename):
                flash(f"'{file.filename}' - image must be png/jpg/jpeg/webp/gif.", "danger")
                return None

            safe = secure_filename(file.filename)
            safe = f"{int(datetime.now().timestamp() * 1000)}_{safe}"

            if USE_S3:
                url = upload_to_s3(file, safe)
                if not url:
                    flash(f"Failed to upload '{file.filename}' to S3.", "danger")
                    return None
                uploaded_filenames.append(url)
            else:
                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe))
                uploaded_filenames.append(safe)

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


@app.errorhandler(500)
def server_error(e):
    """Show a clear message when the DB is unavailable, instead of a generic 500."""
    if _db_pool is None:
        return (
            "<h1>Database not configured</h1>"
            "<p>The site can't reach its database. Check Render logs for details.</p>"
            f"<pre>{_db_error}</pre>",
            500,
        )
    return "<h1>Internal server error</h1><p>Please try again shortly.</p>", 500


# Quick health check — visit /healthz to see DB status without any auth.
@app.route("/healthz")
def healthz():
    if _db_pool is None:
        return f"DB DOWN: {_db_error}", 500
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM products")
            n = cur.fetchone()["n"]
        return f"OK - {n} products in database", 200
    except Exception as e:
        return f"DB query failed: {type(e).__name__}: {e}", 500


# ----------------------------- MAIN -----------------------------------------
init_db()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ScootyBazaar is running!")
    print("  Open: http://127.0.0.1:5000")
    print(f"  Image storage: {'S3 (' + S3_BUCKET + ')' if USE_S3 else 'local /static/images/'}")
    print("=" * 60 + "\n")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
