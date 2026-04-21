#!/bin/bash

APP_DIR="/home/ape01/PROJECT_APE65_A1"
APP_PATH="$APP_DIR/app.py"

echo "------------------------------------------"
echo "  PROJECT_APE65_A1 CLEAN RESTART"
echo "------------------------------------------"

# 1. ปิดกระบวนการเก่าที่อาจค้างอยู่
echo "[1/3] Killing old processes..."
fuser -k 5000/tcp 5020/tcp 2>/dev/null
pkill -TERM -f "python3 app.py"
pkill -TERM -f "rpicam-vid.*--codec mjpeg"
sleep 1
fuser -k 5000/tcp 5020/tcp 2>/dev/null
pkill -KILL -f "python3 app.py"
pkill -KILL -f "rpicam-vid.*--codec mjpeg"

# 2. รอให้ระบบคืนค่าทรัพยากร
echo "[2/3] Waiting for system resources..."
sleep 2

# 3. เริ่มรันโปรแกรม
echo "[3/3] Starting PROJECT_APE65_A1..."
cd "$APP_DIR"

# ตรวจสอบว่ามี Virtual Environment ไหม
if [ -d "venv" ]; then
    source venv/bin/activate
fi

exec python3 app.py
