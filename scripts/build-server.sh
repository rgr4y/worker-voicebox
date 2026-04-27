#!/bin/bash
# Build Python server binary for all platforms

set -e

# Determine platform
PLATFORM=$(rustc --print host-tuple 2>/dev/null || echo "unknown")

echo "Building voicebox-server for platform: $PLATFORM"

# Build Python binary
cd backend

# Check if PyInstaller is installed
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Build binary
python build_binary.py

echo "Build complete!"
