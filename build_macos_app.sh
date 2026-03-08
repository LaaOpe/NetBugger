#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

VERSION="${VERSION:-v0.1.1}"
APP_VERSION="${VERSION#v}"
MAC_ZIP_NAME="NetBugger-macos-${VERSION}.zip"

echo "[1/4] 安装打包依赖..."
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements-macos.txt

echo "[2/4] 清理旧的构建产物..."
"$PYTHON_BIN" - <<'PY'
import os
import shutil

for path in ('build', 'dist', 'NetBugger.spec'):
  if os.path.isdir(path):
    shutil.rmtree(path, ignore_errors=True)
  elif os.path.exists(path):
    os.remove(path)
PY

echo "[3/4] 开始构建 NetBugger.app ..."
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name NetBugger \
  --osx-bundle-identifier com.netbugger.app \
  --exclude-module pystray \
  --exclude-module PIL \
  --add-data "settings.json:." \
  main.py

PLIST_PATH="$SCRIPT_DIR/dist/NetBugger.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PLIST_PATH" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$PLIST_PATH" >/dev/null 2>&1 || true

echo "[4/4] 打包 zip..."
cd "$SCRIPT_DIR/dist"
rm -f "$MAC_ZIP_NAME"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "NetBugger.app" "$MAC_ZIP_NAME"

echo

echo "构建完成: $SCRIPT_DIR/dist/NetBugger.app"
echo "Zip 产物: $SCRIPT_DIR/dist/$MAC_ZIP_NAME"
