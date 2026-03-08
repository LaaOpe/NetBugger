@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if "%VERSION%"=="" set VERSION=v0.1.1
set WIN_ZIP_NAME=NetBugger-windows-%VERSION%.zip

echo [1/4] 安装打包依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt

echo [2/4] 清理旧的构建产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist NetBugger.spec del /f /q NetBugger.spec

echo [3/4] 开始构建 NetBugger.exe ...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name NetBugger ^
  --hidden-import PIL._tkinter_finder ^
  --collect-all pystray ^
  --collect-all PIL ^
  --add-data "settings.json;." ^
  main.py

echo [4/4] 打包 zip...
powershell -NoProfile -Command "Compress-Archive -Path 'dist/NetBugger' -DestinationPath 'dist/%WIN_ZIP_NAME%' -Force"

echo.
echo 构建完成: %CD%\dist\NetBugger
echo Zip 产物: %CD%\dist\%WIN_ZIP_NAME%