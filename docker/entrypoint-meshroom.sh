#!/bin/bash
# Entrypoint script for Meshroom Docker container
# Handles GPU setup, Meshroom validation, and command execution

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Meshroom SfM Engine Initialization ===${NC}"

# Check CUDA availability
echo "Checking CUDA setup..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "⚠️  nvidia-smi not available"

# Check Meshroom installation
echo ""
echo "Checking Meshroom installation..."
python3 << 'EOF'
try:
    import meshroom
    print(f"✓ Meshroom available")
    print(f"  Version: {meshroom.__version__ if hasattr(meshroom, '__version__') else 'unknown'}")
except Exception as e:
    print(f"✗ Meshroom error: {e}")
    exit(1)
EOF

# Check Meshroom command-line tool
echo ""
echo "Checking meshroom_photogrammetry command..."
if command -v meshroom_photogrammetry &> /dev/null; then
    echo "✓ meshroom_photogrammetry command available"
    meshroom_photogrammetry --version || echo "  (version check not available)"
else
    echo "⚠️  meshroom_photogrammetry command not in PATH"
    echo "  Attempting Python-based discovery..."
    python3 << 'EOF'
import subprocess
import os
try:
    result = subprocess.run(['python3', '-m', 'meshroom.cmd', '--help'], capture_output=True)
    print("✓ Meshroom command module available")
except Exception as e:
    print(f"⚠️  Could not verify meshroom command: {e}")
EOF
fi

# Check required packages
echo ""
echo "Checking required packages..."
python3 << 'EOF'
required_packages = [
    ('scipy', 'SciPy'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
    ('opencv', 'OpenCV'),
    ('rembg', 'rembg'),
]

all_ok = True
for pkg_name, pkg_label in required_packages:
    try:
        __import__(pkg_name)
        print(f"✓ {pkg_label}")
    except ImportError:
        print(f"✗ {pkg_label} missing")
        all_ok = False

if not all_ok:
    exit(1)
EOF

# Create output directories if they don't exist
mkdir -p /app/input /app/output /app/logs

echo ""
echo -e "${GREEN}✓ Meshroom SfM Engine Ready${NC}"
echo ""

# Execute the command
exec "$@"
