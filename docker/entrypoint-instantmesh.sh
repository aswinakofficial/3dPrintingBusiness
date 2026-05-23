#!/bin/bash
# Entrypoint for InstantMesh Docker container

set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== InstantMesh Engine Initialization ===${NC}"

python3 << 'EOF'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}GB")
EOF

python3 << 'EOF'
import sys
sys.path.insert(0, '/opt/instantmesh')
packages = [
    ('torch', 'PyTorch'),
    ('diffusers', 'Diffusers'),
    ('einops', 'einops'),
    ('omegaconf', 'OmegaConf'),
    ('trimesh', 'Trimesh'),
    ('PIL', 'Pillow'),
    ('rembg', 'rembg'),
    ('xatlas', 'xatlas'),
    ('nvdiffrast', 'nvdiffrast'),
]
all_ok = True
for pkg_name, label in packages:
    try:
        __import__(pkg_name)
        print(f"✓ {label}")
    except ImportError as e:
        print(f"✗ {label} missing: {e}")
        all_ok = False

# Check InstantMesh src imports
try:
    from src.utils.train_util import instantiate_from_config
    from src.utils.camera_util import get_zero123plus_input_cameras
    from src.utils.mesh_util import save_obj_with_mtl
    print("✓ InstantMesh src utilities")
except ImportError as e:
    print(f"✗ InstantMesh src utilities: {e}")
    all_ok = False

if not all_ok:
    exit(1)
EOF

mkdir -p /app/input /app/output /app/logs

echo ""
echo -e "${GREEN}✓ InstantMesh Engine Ready${NC}"
echo ""

exec "$@"
