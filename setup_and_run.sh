#!/bin/bash
# ============================================================
#   ScootyBazaar - One-click setup for Mac / Linux
#   Creates venv -> installs requirements -> runs app
# ============================================================

echo ""
echo "=========================================="
echo "   ScootyBazaar Setup (Mac/Linux)"
echo "=========================================="
echo ""

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is not installed."
    echo "Install it from https://www.python.org/downloads/ or via your package manager."
    exit 1
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv venv || { echo "[ERROR] venv creation failed"; exit 1; }
else
    echo "[1/3] Virtual environment already exists - skipping."
fi

# Activate venv
echo "[2/3] Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "[3/3] Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "   Setup complete! Starting ScootyBazaar..."
echo "=========================================="
echo ""
echo "   Website: http://127.0.0.1:5000"
echo "   Admin:   http://127.0.0.1:5000/admin/login"
echo "            username: admin  /  password: admin123"
echo ""
echo "   Press Ctrl+C to stop the server"
echo "=========================================="
echo ""

python app.py
