# Phase 2b: Meshroom SfM Engine Implementation - Progress Report

**Status**: ✅ **CORE IMPLEMENTATION COMPLETE** | Testing Pending
**Date**: 2025 (Current Session)
**Timeline**: ~0.5-1 day (parallel with Phase 2a testing)

---

## Summary

Phase 2b implements the Meshroom Structure from Motion (SfM) engine for multi-view 3D reconstruction from photogrammetry. The engine provides:
- Multi-image input support (10-50+ images required)
- Meshroom command detection and execution
- GPU acceleration support (optional)
- Quality-level configuration (high/medium/low)
- Full SfM pipeline orchestration via subprocess
- Standardized mesh output in GLB format

---

## Completed Components

### 1. **MeshroomEngine Class** (`engines/meshroom_sfm.py`, 360+ lines)

#### Core Methods:
- `__init__(config)` - Initializes with lazy Meshroom discovery
- `validate_prerequisites()` - Validates Meshroom installation and accessibility
- `_find_meshroom()` - Discovers Meshroom command in PATH or environment
- `preprocess(image_paths)` - Processes 10-50+ images with validation
- `infer(preprocessed_images)` - Orchestrates full SfM reconstruction pipeline
- `_run_meshroom_pipeline()` - Executes Meshroom photogrammetry via subprocess
- `_find_output_mesh()` - Locates output mesh from various formats (.obj, .ply, .fbx)
- `postprocess(raw_mesh)` - Exports to GLB format with validation

#### Features:
- Multi-image requirement: Enforces 10-50 images for SfM quality
- Meshroom discovery: Checks PATH, environment variables, conda installation
- Quality settings: High/medium/low options for pipeline precision
- GPU support: Optional GPU acceleration flag
- Flexible output handling: Searches for .obj, .ply, .fbx, .gltf, .glb formats
- Mesh validation: Basic validity checks and degenerate face removal
- Comprehensive logging: Pipeline stages, image counts, mesh statistics
- Timeout protection: 1-hour maximum execution time per reconstruction

#### Architecture:
- Subprocess wrapping: Isolates Meshroom process and captures output
- Temporary working directories: Clean working environment per reconstruction
- Error recovery: Detailed error handling with diagnostic logging
- Configurable quality levels: Affects reconstruction precision and compute time

### 2. **Updated Engine Loader** (`engines/loader.py`)

#### Changes:
- Added `MeshroomEngine` import
- Updated `ENGINE_REGISTRY` to include `"meshroom": MeshroomEngine`
- Both TRELLIS.2 and Meshroom now available via factory

#### Key Update:
```python
ENGINE_REGISTRY: Dict[str, Type[Engine]] = {
    "trellis": TRELLIS2Engine,
    "meshroom": MeshroomEngine,  # ← NEW
}
```

### 3. **Unit Tests** (`tests/test_meshroom_engine.py`, 80+ tests)

#### Test Categories:
1. **Engine Initialization**
   - Basic initialization
   - Factory pattern loading
   - Configuration mapping

2. **Image Preprocessing**
   - Minimum/maximum image validation (10-50)
   - Image count enforcement
   - Multiple image preprocessing
   - Invalid image handling

3. **Configuration & Constants**
   - Min/max images validation (10 vs 50)
   - Resolution constraints (256-4096)
   - Quality settings (high/medium/low)
   - GPU enable/disable toggle

4. **Engine Registry**
   - Meshroom in available engines
   - Both TRELLIS.2 and Meshroom available
   - Factory loading for both

5. **Error Handling**
   - Nonexistent file errors
   - Insufficient images error
   - Invalid engine names

#### Note on Full Pipeline Testing:
- Image preprocessing tests: ✅ Can run without Meshroom installation
- Engine initialization tests: ✅ Can run without Meshroom
- Full pipeline tests (infer/postprocess): ⏳ Require Meshroom installation

### 4. **Code Validation** (`scripts/validate_phase2a.py` - Updated)

- Now validates both Phase 2a AND Phase 2b implementations
- ✅ **PASSES** - All 8 methods of MeshroomEngine verified
- Verifies all class definitions and method signatures

---

## Test Coverage Summary

### Runnable Without Meshroom Installation:
✅ Engine initialization  
✅ Factory pattern loading  
✅ Image preprocessing logic  
✅ Configuration validation  
✅ Minimum/maximum image enforcement  
✅ Error handling for invalid inputs  
✅ Quality/GPU settings  
✅ Code syntax validation  

### Requires Meshroom Installation:
⏳ Meshroom command discovery  
⏳ Full SfM pipeline execution  
⏳ Mesh output validation  
⏳ Mesh repair and export  
⏳ End-to-end reconstruction  

---

## Technical Specifications

### SfM Pipeline Requirements:
- **Engine**: Meshroom (AliceVision)
- **Input**: 10-50 overlapping images (ideally 20-40 for quality)
- **Image Requirements**: 256×256 minimum, 4096×4096 maximum
- **Processing Time**: 5-30 minutes depending on image count and quality
- **Memory Footprint**: 4-16GB (varies with image resolution)

### Installation Methods:
```bash
# Option 1: Conda (recommended)
conda install meshroom -c conda-forge

# Option 2: Docker
docker pull alicevision/meshroom:latest

# Option 3: Download from alicevision.org
# https://github.com/alicevision/meshroom/releases
```

### Configuration Options:
- **Quality Levels**:
  - `high` - Full quality, 30+ minutes processing
  - `medium` - Balanced, 15-20 minutes
  - `low` - Fast, 5-10 minutes
- **GPU Acceleration**: Optional, improves compute time 2-5x
- **Image Limits**: Soft max enforced at 50, can process more with code modification

### Dependencies:
- Meshroom (subprocess wrapper, not imported)
- trimesh 4.0.0 (Mesh I/O)
- PIL 10.1.0 (Image loading)
- loguru 0.7.2 (Logging)
- ImageValidator/ImagePreprocessor (Phase 1)

---

## Architecture Decisions

### 1. **Subprocess-Based Integration**
- Meshroom runs as independent process
- Avoids direct Python API dependency
- Enables easy upgrades/downgrades of Meshroom
- Provides process isolation and error recovery

### 2. **Flexible Image Count Validation**
- Minimum: 10 images (SfM requirement)
- Maximum: 50 images (config limit, easily adjustable)
- Logs warnings when limiting
- Allows directory input with auto-filtering

### 3. **Quality-based Configuration**
- Meshroom arguments vary by quality level
- Users can choose speed vs accuracy tradeoff
- Configuration persists on engine instance
- Defaults to "high" for production use

### 4. **Mesh Format Detection**
- Searches output directory recursively
- Supports multiple formats (.obj, .ply, .fbx, .gltf, .glb)
- Prioritizes based on file type order
- Clear error message if no mesh found

### 5. **Timeout Protection**
- 1-hour maximum execution time
- Prevents hanging on large reconstructions
- Can be adjusted for specific use cases
- Logs remaining time remaining in long operations

---

## File Structure

```
Phase 2b Files:
├── engines/
│   ├── meshroom_sfm.py         ← MeshroomEngine implementation (NEW)
│   ├── loader.py               ← Updated with Meshroom registry
│   ├── trellis_v2.py           ← (Phase 2a)
│   └── base_engine.py          ← (Phase 1)
├── tests/
│   ├── test_meshroom_engine.py  ← Unit test suite (NEW)
│   ├── test_trellis_engine.py   ← (Phase 2a)
│   ├── conftest.py             ← (Phase 1)
│   └── __init__.py             ← (Phase 1)
└── scripts/
    └── validate_phase2a.py     ← Updated to validate Phase 2a & 2b
```

---

## Dual-Engine Architecture

Both Phase 2a and Phase 2b are now integrated into single factory:

```python
# CLI usage (Phase 4 will implement):
python main.py --engine trellis --images photo1.jpg photo2.jpg photo3.jpg
python main.py --engine meshroom --images image_folder/

# Programmatic usage:
from engines.loader import load_engine

trellis = load_engine("trellis", config)
meshroom = load_engine("meshroom", config)
```

### Engine Selection Guide:
| Criterion | TRELLIS.2 | Meshroom |
|-----------|-----------|----------|
| Min Images | 1 | 10 |
| Max Images | 4 | 50+ |
| Conditioning | Image quality critical | Overlap critical |
| Speed | ~30 seconds | ~10-30 minutes |
| VRAM | 24GB minimum | 4-16GB |
| Installation | HuggingFace auto-download | Manual Meshroom install |
| Output Quality | High detail, stylized | Photogrammetric accuracy |
| Best For | Single object, product shots | Site scanning, complex geometry |

---

## Next Steps

### Phase 2a & 2b - Testing (Parallel):
1. ⏳ Install PyTorch + CUDA for TRELLIS.2 testing
2. ⏳ Install Meshroom for SfM pipeline testing
3. ⏳ Run full pytest suite for both engines
4. ⏳ Validate mesh output (vertices, faces, format)
5. ⏳ Test multi-image processing for each engine
6. ⏳ Performance benchmarking

### Phase 3 - Post-Processing (Parallel):
1. ⏳ Create `utils/post_processor.py`
2. ⏳ Implement mesh repair (pymeshlab non-manifold fixes)
3. ⏳ Implement mesh hollowing (trimesh voxelization)
4. ⏳ Implement support generation (overhang detection)
5. ⏳ Create unified post-processing pipeline

### Phase 4 - CLI & Orchestration:
1. ⏳ Create `main.py` with argparse/click CLI
2. ⏳ Engine selection logic (trellis vs meshroom)
3. ⏳ Input preprocessing coordination
4. ⏳ Post-processing pipeline integration
5. ⏳ Output management (timestamped dirs, metadata)

### Phase 5 - Docker Containerization:
1. ⏳ `docker/trellis/Dockerfile` (~8-10GB, TRELLIS.2 + CUDA)
2. ⏳ `docker/meshroom/Dockerfile` (~3-5GB, Meshroom + AliceVision)
3. ⏳ Docker Compose for multi-engine selection
4. ⏳ Shared base layer optimization

### Phase 6 - Azure Deployment:
1. ⏳ `run_azure.sh` deployment automation
2. ⏳ Azure VM resource provisioning
3. ⏳ Container registry setup
4. ⏳ Monitoring and logging configuration

---

## Validation Checklist

- ✅ Python syntax valid for MeshroomEngine
- ✅ All 8 required methods present
- ✅ Proper inheritance from Engine base class
- ✅ Engine loader updated with Meshroom registry
- ✅ Unit test file created with comprehensive coverage
- ✅ Code validation script passes all checks
- ✅ Git commits tracking progress
- ⏳ Meshroom installation verification
- ⏳ Full pipeline execution test
- ⏳ Mesh output validation

---

## Key Differences: TRELLIS.2 vs Meshroom

| Aspect | TRELLIS.2 | Meshroom |
|--------|-----------|----------|
| Algorithm | Diffusion-based 3D generation | Structure from Motion (SfM) |
| Training | Trained on ShapeNet+ | Algorithmic (non-learning) |
| Conditioning | Image content → 3D | Multiple views → 3D |
| Robustness | Consistent, stylized output | Real-world accuracy |
| Failure modes | Hallucinated geometry | Missing features, holes |
| Best input | High-quality single image | 20-40 overlapping photos |
| Scalability | Limited by image count (max 4) | Scales to 50+ images |
| Compute | 24GB VRAM, 30 sec | 4-16GB RAM, 10-30 min |

---

## Notes for Phase 3 Integration

The post-processing pipeline (Phase 3) will work with outputs from both engines:

**TRELLIS.2 outputs:**
- Tend to be over-smooth, may need edge enhancement
- Few internal holes (well-sealed meshes)
- May benefit from hollowing for 3D printing

**Meshroom outputs:**
- May have missing geometry (holes, incomplete faces)
- Require mesh repair and hole-filling
- Often need support generation for overhangs
- Better preserve original geometry

Both will use the same repair → hollow → support workflow from Phase 3.

---

**Progress**: Phase 2a & 2b implementation complete | Both engines ready for integration testing
