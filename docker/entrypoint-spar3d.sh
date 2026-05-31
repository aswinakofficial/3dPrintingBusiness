#!/bin/bash
# Entrypoint for SPAR3D (Stable Point-Aware 3D) Docker container

set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== SPAR3D (Stable Point-Aware 3D) Engine Initialization ===${NC}"

python3 << 'EOF'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")
EOF

python3 << 'EOF'
packages = [
    ('torch', 'PyTorch'),
    ('spar3d', 'SPAR3D'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
    ('rembg', 'rembg'),
    ('realesrgan', 'Real-ESRGAN'),
]
all_ok = True
for pkg_name, label in packages:
    try:
        __import__(pkg_name)
        print(f"✓ {label}")
    except ImportError as e:
        print(f"✗ {label} missing: {e}")
        all_ok = False
if not all_ok:
    exit(1)
EOF

if [ -z "$HF_TOKEN" ]; then
    echo "WARNING: HF_TOKEN not set. stabilityai/stable-point-aware-3d is a gated model."
    echo "Accept the license at https://huggingface.co/stabilityai/stable-point-aware-3d"
    echo "then set HF_TOKEN in your environment or Container Apps secrets."
fi

mkdir -p /app/input /app/output /app/logs

echo ""
echo -e "${GREEN}✓ SPAR3D Engine Ready${NC}"
echo ""

exec "$@"
