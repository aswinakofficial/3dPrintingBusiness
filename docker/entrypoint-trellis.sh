#!/bin/bash
# Entrypoint script for TRELLIS.2 Docker container
# Handles GPU setup, environment validation, and command execution

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== TRELLIS.2 Engine Initialization ===${NC}"

# Check CUDA availability
echo "Checking CUDA setup..."
python3 << 'EOF'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")
else:
    print("⚠️  WARNING: CUDA not available, will use CPU (slow)")
EOF

# Check HuggingFace model availability
echo ""
echo "Checking HuggingFace connectivity..."
python3 << 'EOF'
try:
    from transformers import AutoModel
    print("✓ HuggingFace transformers available")
except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)
EOF

# Check required packages
echo ""
echo "Checking required packages..."
python3 << 'EOF'
required_packages = [
    ('torch', 'PyTorch'),
    ('transformers', 'HuggingFace Transformers'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
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
echo -e "${GREEN}✓ TRELLIS.2 Engine Ready${NC}"
echo ""

# Execute the command
exec "$@"
