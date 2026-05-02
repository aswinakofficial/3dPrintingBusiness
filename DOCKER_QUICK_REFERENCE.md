# 3D Figurine Lab - Docker Quick Reference

## Build Images

### Using docker-compose
```bash
# Build all images
docker-compose build

# Build specific service
docker-compose build trellis-engine
docker-compose build meshroom-engine
```

### Using docker build directly
```bash
# Build TRELLIS.2
docker build -f docker/Dockerfile.trellis -t 3dfigurine-trellis:latest .

# Build Meshroom  
docker build -f docker/Dockerfile.meshroom -t 3dfigurine-meshroom:latest .

# Build with specific version tag
docker build -f docker/Dockerfile.trellis -t 3dfigurine-trellis:v1.0 .
```

### Using build script
```bash
chmod +x docker/build.sh

# Build both images
./docker/build.sh build

# Build single image
./docker/build.sh build-trellis
./docker/build.sh build-meshroom

# List images
./docker/build.sh list

# Test containers
./docker/build.sh test-trellis
./docker/build.sh test-meshroom
```

## Run Containers

### TRELLIS.2 Engine

```bash
# Single image processing
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/logs:/app/logs \
  3dfigurine-trellis:latest \
  python main.py --engine trellis --images /app/input/photo.jpg

# Multi-image processing  
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  3dfigurine-trellis:latest \
  python main.py --engine trellis --images /app/input/photo*.jpg --supports --hollow
```

### Meshroom SfM Engine

```bash
# Process image directory (10-50 images)
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  3dfigurine-meshroom:latest \
  python main.py --engine meshroom --directory /app/input

# With custom post-processing
docker run --rm \
  --gpus all \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  3dfigurine-meshroom:latest \
  python main.py --engine meshroom --directory /app/input --repair --hollow --supports
```

## Docker Compose

### Start services

```bash
# TRELLIS.2 service
docker-compose run --rm trellis-engine

# Meshroom service
docker-compose run --rm meshroom-engine

# Interactive shell
docker-compose run --rm trellis-engine bash
```

## GPU Configuration

### Check GPU availability

```bash
# On host
nvidia-smi

# In container
docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi
```

### Set specific GPU

```bash
# Use GPU 0 only
docker run --rm \
  --gpus device=0 \
  -e CUDA_VISIBLE_DEVICES=0 \
  ...

# Use multiple GPUs (if available)
docker run --rm \
  --gpus device=0,1 \
  -e CUDA_VISIBLE_DEVICES=0,1 \
  ...
```

### Enable all GPUs

```bash
docker run --rm --gpus all ...
```

## Data Management

### View output
```bash
# List generated meshes
ls -lh output/trellis/*/final_mesh.glb

# View metadata
cat output/trellis/*/metadata.json | python -m json.tool
```

### Clean up
```bash
# Remove old sessions
rm -rf output/trellis/20260501_*

# Clean Docker images
docker rmi 3dfigurine-trellis:latest
./docker/build.sh clean
```

## Troubleshooting

### CUDA not available
```bash
# Verify NVIDIA Docker runtime is installed
docker info | grep nvidia

# Install if missing (Ubuntu)
sudo apt-get install nvidia-docker2
sudo systemctl restart docker
```

### Out of memory
```bash
# Check available VRAM
docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi

# TRELLIS.2 requires 24GB
# Meshroom: 6-12GB (scales with images)
```

### Container won't start
```bash
# Run with verbose logging
docker run -it --gpus all 3dfigurine-trellis:latest bash

# Inside container, debug:
python3 -c "import torch; print(torch.cuda.is_available())"
python3 -c "from transformers import AutoModel; print('OK')"
```

## Monitoring

### Check container logs
```bash
docker logs <container_id>

# Follow logs
docker logs -f <container_id>
```

### Monitor resource usage
```bash
docker stats

# Memory/CPU during processing
watch nvidia-smi
```

## Production Deployment

### Push to Azure Container Registry
```bash
# Login
az acr login --name myregistry

# Tag image
docker tag 3dfigurine-trellis:latest myregistry.azurecr.io/3dfigurine-trellis:v1.0

# Push
docker push myregistry.azurecr.io/3dfigurine-trellis:v1.0

# Deploy with Azure CLI (Phase 6)
az container create \
  --resource-group mygroup \
  --name 3dfigurine-trellis \
  --image myregistry.azurecr.io/3dfigurine-trellis:v1.0 \
  --cpu 4 --memory 25 \
  --port 8080
```

## Performance Tips

1. **Pre-download models**: First run downloads HuggingFace models (5-10 min)
   ```bash
   docker run --rm -it 3dfigurine-trellis:latest python -c "from transformers import AutoModel; AutoModel.from_pretrained('microsoft/TRELLIS.2-4B')"
   ```

2. **Use volume mounts** for faster I/O instead of copying files

3. **Reuse containers** for multiple runs to avoid startup overhead

4. **Use specific GPU** with `CUDA_VISIBLE_DEVICES` if multi-GPU system

5. **Monitor resources** to ensure sufficient VRAM/CPU available

## Common Commands Summary

| Task | Command |
|------|---------|
| Build all | `docker-compose build` |
| Build one | `./docker/build.sh build-trellis` |
| List images | `./docker/build.sh list` |
| Test container | `./docker/build.sh test-trellis` |
| Run TRELLIS.2 | `docker run --rm --gpus all -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output 3dfigurine-trellis:latest python main.py --engine trellis --images /app/input/*.jpg` |
| Run Meshroom | `docker run --rm --gpus all -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output 3dfigurine-meshroom:latest python main.py --engine meshroom --directory /app/input` |
| Interactive shell | `docker-compose run --rm trellis-engine bash` |
| Clean images | `./docker/build.sh clean` |

