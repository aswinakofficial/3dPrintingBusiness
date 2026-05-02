# 3D Figurine Lab – Production Pipeline

Convert customer photos to print-ready 3D figurine STL files using dual AI engines (TRELLIS.2 + Meshroom).

## Quick Start

### Prerequisites
- Python 3.10+
- NVIDIA GPU with 24GB+ VRAM (A10, A100 recommended)
- CUDA 12.4
- Docker + NVIDIA runtime
- Azure VM or local GPU machine

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/3dPrintingBusiness.git
cd 3dPrintingBusiness

# Create Python virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### TRELLIS.2 Engine (Fast, 1-4 images)

```bash
# Single image
python main.py --input path/to/photo.jpg \
               --engine trellis \
               --output-dir ./output

# Multi-image (best quality with 3-4 complementary angles)
python main.py --input photo_front.jpg photo_side.jpg photo_back.jpg \
               --engine trellis \
               --output-dir ./output
```

**Characteristics**:
- ⚡ Fast: 3-17 seconds per image (depending on GPU)
- 🎨 Stylized output with textures/PBR materials
- 📸 Optimal for 1-4 images (multi-view conditioning)
- 💾 GPU memory: 24GB+ required

### Meshroom Engine (Photogrammetry, 10-50+ images)

```bash
# Process directory with many overlapping photos
python main.py --input ./photos_directory/ \
               --engine meshroom \
               --output-dir ./output

# Or specify image list
python main.py --input img_001.jpg img_002.jpg img_003.jpg ... img_050.jpg \
               --engine meshroom \
               --output-dir ./output
```

**Characteristics**:
- 🔍 Photogrammetry-based (Structure-from-Motion)
- 📷 Requires 10-50+ overlapping images (360° around subject)
- ⏱️ Slower: 5-30 minutes depending on image count
- 🎯 Captures fine geometric detail
- GPU optional (beneficial for MVS/dense matching)

### List Available Engines

```bash
python main.py --list-engines
```

## Output

Both engines produce:
- **Final output**: `output/final/{input_name}_final.stl` (print-ready, binary format)
- **Intermediate files**: `output/{engine}/{input_name}_raw.*` (for debugging)
- **Logs**: `logs/pipeline_*.log` (JSON structured logs)

## Configuration

Edit `config.yaml` to customize:
- Engine selection (enabled/disabled per engine)
- Mesh repair settings (hole size, manifold validation)
- Hollowing parameters (wall thickness, voxel resolution)
- Support generation (angle threshold, diameter)
- Print profiles (figurine sizes: standard/detailed/miniature)

## Directory Structure

```
3dPrintingBusiness/
├── main.py                 # CLI entry point
├── config.yaml             # Configuration (engines, post-processing)
├── requirements.txt        # Python dependencies
├── README.md               # This file

├── input/                  # Place input images here
├── output/                 # Generated meshes and STLs
│   ├── trellis/
│   ├── meshroom/
│   └── final/
├── logs/                   # Pipeline execution logs

├── engines/
│   ├── base_engine.py      # Abstract engine interface
│   ├── trellis_v2.py       # TRELLIS.2 implementation
│   └── meshroom.py         # Meshroom SfM implementation

├── utils/
│   ├── logger.py           # Structured logging
│   ├── pre_processor.py    # Image validation & preprocessing
│   └── post_processor.py   # Mesh repair, hollowing, supports

├── docker/
│   ├── trellis/
│   │   └── Dockerfile      # TRELLIS.2 container
│   ├── meshroom/
│   │   └── Dockerfile      # Meshroom container
│   └── shared/
│       └── Dockerfile.base # Shared CUDA base image

└── scripts/
    ├── run_local.sh        # Local GPU execution
    ├── run_azure.sh        # Azure VM deployment
    └── compare.sh          # Compare engines on same input
```

## Docker Deployment

### Build TRELLIS.2 Docker Image

```bash
docker build -t 3dfigurine-trellis:latest -f docker/trellis/Dockerfile .

# Test
docker run --gpus all \
  -v $(pwd)/input:/workspace/input \
  -v $(pwd)/output:/workspace/output \
  3dfigurine-trellis:latest \
  --input input/test.jpg --engine trellis --output-dir output
```

### Build Meshroom Docker Image

```bash
docker build -t 3dfigurine-meshroom:latest -f docker/meshroom/Dockerfile .

# Test with image directory
docker run --gpus all \
  -v $(pwd)/input:/workspace/input \
  -v $(pwd)/output:/workspace/output \
  3dfigurine-meshroom:latest \
  --input input/photos_dir --engine meshroom --output-dir output
```

## Azure Deployment

### Prerequisites
- Azure GPU VM (Standard_A100_v4 or Standard_A10, Ubuntu 22.04)
- NVIDIA drivers + CUDA 12.4 installed
- Docker + NVIDIA runtime configured

### Deploy

```bash
# Option 1: Run with local script
./scripts/run_azure.sh --input photos_dir --engine meshroom

# Option 2: Direct Azure VM SSH
ssh azureuser@your-vm-ip
cd /opt/3dfigurine-lab
docker run --gpus all \
  -v /data/input:/workspace/input \
  -v /data/output:/workspace/output \
  3dfigurine-trellis:latest \
  --input input/photo.jpg --engine trellis
```

## Performance Metrics

### TRELLIS.2 (GPU: A100 40GB)
- **Single image**: ~5 seconds
- **3 images (multi-view)**: ~12 seconds
- **GPU memory peak**: ~22GB
- **Output quality**: Ultra (voxel-based, stylized)

### Meshroom (GPU: A100 40GB)
- **15 images**: ~10-15 minutes
- **30 images**: ~15-25 minutes
- **50 images**: ~25-35 minutes
- **GPU memory**: 8-16GB (MVS step)
- **Disk space**: ~10GB temporary space per job

## Troubleshooting

### TRELLIS.2: "CUDA out of memory"
- Requires 24GB+ VRAM
- If running A10 (24GB), close other GPU processes
- Fallback: Use smaller image (512 resolution in config)

### Meshroom: Processing very slow
- CPU-only mode active (GPU not available)
- Enable GPU in config.yaml: `meshroom.use_gpu: true`
- Add more images (10-20 optimal balance)

### Mesh repair fails with manifold error
- Try increasing `mesh_repair.max_hole_size` in config
- Manually review mesh in MeshLab/Blender
- Contact support if persistent

## Development

### Run Tests

```bash
pytest tests/ -v --cov=.
```

### Code Quality

```bash
black .
flake8 .
```

## License

Proprietary – 3D Printing Business

## Support

For issues or feature requests, contact: support@3dprintingbusiness.com
