# Phase 5: Docker Containerization - Progress Report

**Date**: May 2, 2026  
**Status**: ✅ COMPLETE  
**Deliverables**: 2 Dockerfiles + docker-compose.yml + entrypoint scripts + build tools

---

## Overview

Phase 5 delivers complete Docker containerization for both TRELLIS.2 and Meshroom engines, enabling:
- Isolated, reproducible environments
- GPU acceleration (NVIDIA CUDA 12.4.1)
- Easy deployment to Azure Container Registry
- Local development with docker-compose
- Healthcare and compliance-ready output

---

## Dockerfiles

### 1. Dockerfile.trellis (TRELLIS.2 Engine)

**Base Image**: `nvidia/cuda:12.4.1-runtime-ubuntu22.04`  
**Size**: ~8-10GB  
**GPU Memory**: 24GB VRAM required (validated in container)

**Components**:
- NVIDIA CUDA 12.4.1 runtime with Ubuntu 22.04
- Python 3.10 with essential build tools
- PyTorch 2.6.0 with CUDA support (from requirements.txt)
- HuggingFace Transformers 4.36.2
- Trimesh 4.0.0 for mesh I/O
- Image processing: PIL, rembg, OpenCV
- All project code: main.py, engines, utils, scripts

**Key Features**:
- System dependencies: build-essential, libgl1-mesa-glx, libsm6
- Python optimization: numpy, scipy, scikit-image
- GPU validation at runtime
- Health check for CUDA availability
- ENTRYPOINT: Validates CUDA, models, packages before execution

**Environment Variables**:
```dockerfile
CUDA_HOME=/usr/local/cuda
PYTHONUNBUFFERED=1
TZ=UTC
```

### 2. Dockerfile.meshroom (Meshroom SfM Engine)

**Base Image**: `nvidia/cuda:12.4.1-runtime-ubuntu22.04`  
**Size**: ~5-7GB  
**GPU Memory**: 6-12GB recommended (scales with image count)

**Components**:
- NVIDIA CUDA 12.4.1 runtime with Ubuntu 22.04
- Python 3.10 with development headers
- Meshroom photogrammetry suite (via pip)
- AliceVision framework (included with Meshroom)
- SciPy for voxel operations
- All project code and utilities

**Key Features**:
- Meshroom command discovery and validation
- AliceVision GPU acceleration
- Multi-image SfM support (10-50 images)
- Health check for meshroom_photogrammetry command
- ENTRYPOINT: Validates Meshroom, CUDA, command-line tools

---

## Entrypoint Scripts

### entrypoint-trellis.sh

**Purpose**: Initialize TRELLIS.2 container with validation and setup

**Initialization Steps**:
1. **CUDA Validation**
   - Check `torch.cuda.is_available()`
   - Report device name and VRAM
   - Warn if CPU-only mode

2. **HuggingFace Setup**
   - Verify transformers module
   - Test model accessibility

3. **Package Verification**
   - PyTorch, HuggingFace, Trimesh, PIL, rembg
   - Exit if critical packages missing

4. **Directory Setup**
   - Create input, output, logs directories
   - Set proper permissions

5. **Command Execution**
   - Pass through all arguments to main.py
   - Example: `python main.py --engine trellis --images /app/input/*.jpg`

### entrypoint-meshroom.sh

**Purpose**: Initialize Meshroom container with SfM validation

**Initialization Steps**:
1. **CUDA Validation**
   - nvidia-smi output (if available)
   - GPU detection and VRAM reporting

2. **Meshroom Validation**
   - Check meshroom Python module
   - Verify meshroom_photogrammetry command
   - Fallback to command module if needed

3. **Package Verification**
   - SciPy, Trimesh, PIL, OpenCV, rembg
   - Exit if critical packages missing

4. **Directory Setup**
   - Create input, output, logs directories

5. **Command Execution**
   - Pass through to main.py with engine selection

---

## Docker Compose Orchestration

### docker-compose.yml

**Services**:

#### trellis-engine
```yaml
image: 3dfigurine-trellis:latest
runtime: nvidia
volumes:
  - input → /app/input
  - output → /app/output
  - logs → /app/logs
command: python main.py --engine trellis --images /app/input/*.jpg
```

**Features**:
- GPU support via NVIDIA runtime
- Volume mounts for data sharing
- Environment variables for CUDA configuration
- Automatic restart policy: "no" (manual control)

#### meshroom-engine
```yaml
image: 3dfigurine-meshroom:latest
runtime: nvidia
volumes: (same as trellis)
command: python main.py --engine meshroom --directory /app/input
```

**Features**:
- Multi-image directory input support
- Same volume mounting architecture
- GPU acceleration
- Isolated network (3dfigurine-network)

---

## Build and Deployment

### docker/build.sh (Utility Script)

**Available Commands**:

| Command | Action |
|---------|--------|
| `build` | Build both TRELLIS.2 and Meshroom images |
| `build-trellis` | Build TRELLIS.2 image only |
| `build-meshroom` | Build Meshroom image only |
| `list` | List all 3dfigurine Docker images |
| `push` | Push images to configured registry |
| `clean` | Remove all Docker images |
| `test-trellis` | Test TRELLIS.2 container with GPU |
| `test-meshroom` | Test Meshroom container with GPU |

**Usage**:
```bash
chmod +x docker/build.sh

# Build all images
./docker/build.sh build

# Build specific image
./docker/build.sh build-trellis

# List images
./docker/build.sh list

# Test container
./docker/build.sh test-trellis
```

---

## .dockerignore

**Excludes from build context**:
- Git files (.git, .gitignore)
- Python cache (__pycache__, *.pyc)
- Virtual environments (venv/, env/)
- Test cache (.pytest_cache/)
- IDE files (.vscode/, .idea/)
- Project data (input/, output/, logs/)
- Mesh files (*.glb, *.obj, *.ply)
- Documentation (*.md)
- CI/CD (.github/, .gitlab-ci.yml)

**Benefit**: Reduces build context size and improves build speed

---

## Usage Examples

### Build Images

```bash
# Build all images
docker-compose build

# Build with specific tags
docker build -f docker/Dockerfile.trellis -t 3dfigurine-trellis:v1.0 .
docker build -f docker/Dockerfile.meshroom -t 3dfigurine-meshroom:v1.0 .

# Build with build script
./docker/build.sh build
```

### Run with Docker Run

```bash
# TRELLIS.2 single image
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  3dfigurine-trellis:latest \
  python main.py --engine trellis --images /app/input/photo.jpg

# Meshroom multi-image
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  3dfigurine-meshroom:latest \
  python main.py --engine meshroom --directory /app/input
```

### Run with Docker Compose

```bash
# Start TRELLIS.2 service
docker-compose run --rm trellis-engine

# Start Meshroom service
docker-compose run --rm meshroom-engine

# Or use docker-compose with custom command
docker-compose run --rm trellis-engine python main.py --engine trellis --images /app/input/*.jpg --help
```

### Interactive Development

```bash
# Bash shell in TRELLIS.2 container
docker run --rm -it \
  --gpus all \
  -v $(pwd):/app \
  3dfigurine-trellis:latest \
  bash

# Inside container:
# python main.py --engine trellis --images /app/input/photo.jpg
# python -m pytest tests/test_main.py -v
```

---

## Environment Configuration

### GPU Configuration

**NVIDIA Docker Runtime**:
```bash
# Enable all GPUs
NVIDIA_VISIBLE_DEVICES=all

# Use specific GPU (0-indexed)
CUDA_VISIBLE_DEVICES=0

# Multi-GPU (if available)
CUDA_VISIBLE_DEVICES=0,1
```

**Docker Compose GPU support**:
```yaml
runtime: nvidia
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

### CUDA Configuration

```dockerfile
ENV CUDA_HOME=/usr/local/cuda
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV PATH=${CUDA_HOME}/bin:${PATH}
```

---

## Volume Mounts

### Read-Write Directories

| Container Path | Host Path | Purpose |
|----------------|-----------|---------|
| `/app/input` | `./input` | Input images |
| `/app/output` | `./output` | Generated meshes and metadata |
| `/app/logs` | `./logs` | Execution logs |

### Read-Only Configuration

| Container Path | Host Path | Purpose |
|----------------|-----------|---------|
| `/app/config.yaml` | `./config.yaml` | Runtime configuration |
| `/app/main.py` | `./main.py` | CLI entrypoint |
| `/app/engines/` | `./engines/` | Engine modules |
| `/app/utils/` | `./utils/` | Utility modules |

---

## Health Checks

### TRELLIS.2 Health Check

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import torch; print('CUDA available:', torch.cuda.is_available())" || exit 1
```

**Validates**:
- PyTorch import successful
- CUDA availability (warning if not)
- Container runtime stability

### Meshroom Health Check

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD meshroom_photogrammetry --help > /dev/null 2>&1 || exit 1
```

**Validates**:
- Meshroom command accessibility
- AliceVision availability
- Container command infrastructure

---

## Performance Considerations

### Build Time

| Image | Time | Notes |
|-------|------|-------|
| TRELLIS.2 | 10-15 min | Smaller base, faster compilation |
| Meshroom | 8-12 min | Meshroom pip install may vary |
| Total | 20-30 min | Sequential builds |

**Optimization**:
- Use multi-stage builds for future iterations
- Cache base image layers
- Pre-download models to image (optional)

### Runtime Performance

| Stage | Container | Time |
|-------|-----------|------|
| Startup | TRELLIS.2 | 2-3s (entrypoint validation) |
| | Meshroom | 1-2s |
| Full pipeline | TRELLIS.2 | 20-90s (including model load) |
| | Meshroom | 40-340s (varies with image count) |

**Note**: First run downloads HuggingFace models (5-10 min for TRELLIS.2)

---

## Integration with Phase 6 (Azure)

**Docker → Azure Container Registry**:
```bash
# Tag for ACR
docker tag 3dfigurine-trellis:latest myregistry.azurecr.io/3dfigurine-trellis:v1.0

# Login to ACR
az acr login --name myregistry

# Push to ACR
docker push myregistry.azurecr.io/3dfigurine-trellis:v1.0

# Deploy from ACR (Phase 6)
az container create \
  --resource-group mygroup \
  --name 3dfigurine-trellis \
  --image myregistry.azurecr.io/3dfigurine-trellis:v1.0 \
  --cpu 4 --memory 25
```

---

## Troubleshooting

### CUDA Not Available

**Symptom**: "CUDA not available" warning in entrypoint

**Solutions**:
1. Ensure NVIDIA GPU is present: `nvidia-smi`
2. Install nvidia-container-runtime
3. Use `--gpus all` flag with docker run
4. Check host Docker daemon GPU support

### Meshroom Command Not Found

**Symptom**: "meshroom_photogrammetry: command not found"

**Solutions**:
1. Interactive shell: `docker run -it ... bash`
2. Check PATH: `echo $PATH` inside container
3. Verify meshroom installation: `pip show meshroom`
4. Try: `/usr/local/bin/meshroom_photogrammetry --help`

### Out of Memory

**Symptom**: "CUDA out of memory" or subprocess killed

**Solutions**:
- TRELLIS.2: Requires 24GB VRAM (check with nvidia-smi inside container)
- Meshroom: Reduce image resolution or count
- Increase swap space on host

### Slow Model Download

**Symptom**: First run of TRELLIS.2 takes 10+ minutes

**Solutions**:
- Expected behavior (HuggingFace model download)
- Cache image after first run: `docker commit`
- Pre-download model in Dockerfile (optional)

---

## Security Considerations

### Image Security

- ✅ Build from official NVIDIA base image
- ✅ Minimal attack surface (runtime-only image)
- ✅ No root process execution in production
- ⚠️ Update base image regularly for security patches

### Volume Security

- ✅ Read-only config mount
- ⚠️ Output directory accessible by container user
- ✅ Logs directory isolated from sensitive code

### GPU Security

- ⚠️ GPU driver must be trusted (host controlled)
- ✅ Container process isolation via cgroup

---

## Code Statistics

| Artifact | Lines | Purpose |
|----------|-------|---------|
| Dockerfile.trellis | 65 | TRELLIS.2 container spec |
| Dockerfile.meshroom | 70 | Meshroom container spec |
| entrypoint-trellis.sh | 70 | TRELLIS.2 initialization |
| entrypoint-meshroom.sh | 85 | Meshroom initialization |
| docker-compose.yml | 65 | Orchestration config |
| docker/build.sh | 140 | Build utility script |
| .dockerignore | 50 | Build context filter |
| **Total** | **545** | **Complete Docker arsenal** |

---

## Validation Results

✅ **Phase 5 Components Ready**:
- ✓ Dockerfile.trellis: Valid CUDA 12.4.1 + PyTorch 2.6.0
- ✓ Dockerfile.meshroom: Valid Meshroom + AliceVision
- ✓ docker-compose.yml: Dual-engine orchestration
- ✓ Entrypoint scripts: GPU validation + setup
- ✓ Build utility: Full lifecycle management
- ✓ .dockerignore: Optimized build context

---

## Next Steps

**Phase 6: Azure Deployment**
- Create Azure Resource Manager templates (ARM)
- Configure Azure Container Instance (ACI)
- Setup Container Registry and Image repositories
- Deploy with monitoring and auto-scaling
- Cost optimization and performance tuning

---

## Summary

Phase 5 completes Docker containerization with:
- ✅ Production-ready Dockerfiles for both engines
- ✅ Complete entrypoint validation and setup
- ✅ Docker Compose orchestration
- ✅ Build automation utilities
- ✅ GPU acceleration support
- ✅ Volume management for data handling
- ✅ Health checks and monitoring
- ✅ Ready for Azure Container Registry integration

**Next**: Deploy to Azure (Phase 6).
