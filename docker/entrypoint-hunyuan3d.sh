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
import sys
# Path ordering matters:
#   hy3dpaint first — textureGenPipeline imports utils.simplify_mesh_utils from hy3dpaint/utils/
#   hy3dshape outer dir — nested pkg: hy3dshape/hy3dshape/__init__.py (outer has no __init__)
#   space root — any other space-level imports
sys.path.insert(0, "/opt/hunyuan3d-space/hy3dpaint")
sys.path.insert(0, "/opt/hunyuan3d-space/hy3dshape")
sys.path.insert(0, "/opt/hunyuan3d-space")
packages = [
    ('torch', 'PyTorch'),
    ('hy3dshape', 'hy3dshape (shape gen)'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
    ('rembg', 'rembg'),
]
all_ok = True
for pkg_name, label in packages:
    try:
        __import__(pkg_name)
        print(f"✓ {label}")
    except ImportError as e:
        print(f"✗ {label} missing: {e}")
        all_ok = False
# cached_download removed from huggingface_hub ≥ 0.17; shim before import
import huggingface_hub as _hfhub
if not hasattr(_hfhub, 'cached_download'):
    _hfhub.cached_download = _hfhub.hf_hub_download
# textureGenPipeline check is advisory — engine falls back to untextured GLB
try:
    import textureGenPipeline  # noqa: F401
    print("✓ textureGenPipeline (texture paint)")
except Exception as e:
    print(f"⚠ textureGenPipeline unavailable: {e} (will fall back to untextured GLB)")
if not all_ok:
    exit(1)
EOF

mkdir -p /app/input /app/output /app/logs

echo ""
echo -e "${GREEN}✓ Hunyuan3D-2 Engine Ready${NC}"
echo ""

exec "$@"
