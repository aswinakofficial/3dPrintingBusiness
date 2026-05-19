#!/bin/bash
# Entrypoint for Hunyuan3D-2 Docker container

set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== Hunyuan3D-2 Engine Initialization ===${NC}"

echo "Checking CUDA setup..."
python3 << 'EOF'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")
EOF

echo ""
echo "Checking hy3dgen packages..."
python3 << 'EOF'
packages = [
    ('torch', 'PyTorch'),
    ('hy3dgen.shapegen', 'hy3dgen.shapegen'),
    ('hy3dgen.texgen', 'hy3dgen.texgen'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
    ('rembg', 'rembg'),
]
all_ok = True
for pkg_name, label in packages:
    try:
        __import__(pkg_name)
        print(f"✓ {label}")
    except ImportError:
        print(f"✗ {label} missing")
        all_ok = False
if not all_ok:
    exit(1)
EOF

mkdir -p /app/input /app/output /app/logs

echo ""
echo -e "${GREEN}✓ Hunyuan3D-2 Engine Ready${NC}"
echo ""

exec "$@"
