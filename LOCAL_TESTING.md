# Phase 1: Local Testing Guide (No Azure, $0 Cost)

## Overview
Before upgrading to Pay-As-You-Go Azure, validate all code changes locally using this guide. This covers linting, format checking, and API validation without running GPU inference.

---

## Quick Start (5 minutes)

```bash
# Activate venv
source venv/bin/activate

# Run linting & formatting checks (should pass)
python -m black --check .
python -m flake8 --count

# Expected: 0 errors
```

✅ **If both pass, your code is ready for Azure testing.**

---

## Detailed Testing Phases

### Phase 1A: Code Quality (No GPU, ~2 minutes)

**Run linting & formatting:**
```bash
source venv/bin/activate

# 1. Check code format
python -m black --check .
# Expected output: "All done! ... files would be reformatted" or "All done! ... left unchanged"

# 2. Check lint errors
python -m flake8 --count
# Expected output: "0" (no errors)

# 3. (Optional) Run unittest for main pipeline logic
python -m pytest tests/test_main.py -v --tb=short \
  -m "not cuda" \
  -k "test_config or test_pipeline_session"
# Expected: Most config tests pass (some pipeline tests may fail due to missing PyTorch)
```

**What this validates:**
- ✅ Code formatting matches black standard (enforced in CI)
- ✅ No lint violations (flake8 checks)
- ✅ Config loading & path handling works
- ✅ Basic config utilities work

---

### Phase 1B: API Endpoint Validation (No Database, ~5 minutes)

**Start the FastAPI server locally:**
```bash
source venv/bin/activate

# Terminal 1: Start the API
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860 --reload
# Output: "Uvicorn running on http://0.0.0.0:7860"
```

**Terminal 2: Test endpoints manually:**
```bash
source venv/bin/activate

# 1. Test /engines endpoint
curl http://localhost:7860/engines | python -m json.tool | head -20
# Expected: List of 7 engines (trellis, meshroom, hunyuan3d, triposg, sf3d, spar3d, instantmesh)

# 2. Test /jobs list (empty at first)
curl http://localhost:7860/jobs | python -m json.tool
# Expected: Empty array []

# 3. Test POST /jobs with an image file (without actually running inference)
# First, create a dummy image:
python -c "from PIL import Image; Image.new('RGB', (512, 512)).save('/tmp/test.jpg')"

# Then submit (this will fail at the Azure step, which is OK):
curl -X POST http://localhost:7860/jobs \
  -F "engine=triposg" \
  -F "gpu_sku=T4" \
  -F "max_runtime_minutes=15" \
  -F "generate_views=false" \
  -F "target_height_mm=100" \
  -F "images=@/tmp/test.jpg" \
  | python -m json.tool
# Expected: Either success (job created) or error about Azure connection (which is OK)
```

**What this validates:**
- ✅ FastAPI server starts without errors
- ✅ /engines endpoint returns correct metadata
- ✅ /jobs endpoint works (lists jobs, returns has_inputs field)
- ✅ UI form submission logic works
- ✅ Database initialization works (if it gets to job creation)

---

### Phase 1C: UI Visual Testing (No Backend, ~10 minutes)

**Start the API server (as above):**
```bash
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860 --reload
```

**Open browser and test:**
1. Go to `http://localhost:7860`
2. **Test Engine Selection:**
   - Click engine cards (trellis, sf3d, meshroom, etc.)
   - Verify they highlight and show image count hints
3. **Test Image Upload:**
   - Drag & drop an image or click upload
   - Verify thumbnail appears
   - Verify image count hint updates
4. **Test Engine Suggestion:**
   - Upload 1 image → should suggest TripoSG
   - Upload 2-6 images → should suggest InstantMesh
5. **Test Job History:**
   - Click "History" tab (will be empty initially)
   - Verify "No jobs yet" message
6. **Test Resubmit UI:**
   - (After submitting a job) Failed jobs should show resubmit button
   - Click resubmit → should open modal
   - Verify modal shows GPU/runtime override options

**What this validates:**
- ✅ Frontend loads without JavaScript errors
- ✅ Form validation works
- ✅ Modal opens/closes correctly
- ✅ Resubmit button appears on failed jobs
- ✅ No blocking UI bugs

---

## Testing Checklist

Before upgrading to Azure, ensure all of these pass:

```
Code Quality:
  ☐ black --check . passes (0 formatting errors)
  ☐ flake8 passes (0 lint errors)
  ☐ pytest tests/test_main.py::TestConfig passes

API Endpoints:
  ☐ POST /jobs accepts form data (doesn't need to run)
  ☐ GET /jobs returns list with has_inputs field
  ☐ GET /engines returns all 7 engines with metadata
  ☐ FastAPI server starts without errors

UI/Frontend:
  ☐ http://localhost:7860 loads in browser
  ☐ Engine cards are clickable
  ☐ Image upload works
  ☐ Job history tab loads
  ☐ Resubmit button visible on failed jobs (mock data needed)
  ☐ Resubmit modal opens/closes

New Features (Resubmit):
  ☐ Resubmit button disabled when inputs missing
  ☐ Resubmit button enabled when inputs present
  ☐ Resubmit modal shows override options (GPU, runtime, height)
  ☐ has_inputs field in /jobs response
```

---

## Running Tests in Stages

### Stage 1: Linting Only (30 seconds)
```bash
source venv/bin/activate
python -m black --check . && python -m flake8 --count && echo "✅ All checks passed!"
```

### Stage 2: Basic API Test (2 minutes)
```bash
source venv/bin/activate
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860 &
sleep 2
curl -s http://localhost:7860/engines | python -m json.tool | head -20
pkill -f uvicorn
```

### Stage 3: Full UI Manual Test (10 minutes)
```bash
source venv/bin/activate
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860 --reload
# Then open browser and click around (use the checklist above)
```

---

## Common Issues & Fixes

### Issue: `ModuleNotFoundError: torch`
**Solution:** This is expected locally. Use `-m "not cuda"` flag in pytest to skip GPU-dependent tests.
```bash
python -m pytest tests/ -m "not cuda" -v
```

### Issue: Port 7860 already in use
**Solution:** Kill the old process or use a different port:
```bash
lsof -i :7860  # Find process ID
kill -9 <PID>  # Kill it
# Or use different port:
python -m uvicorn ui.app:app --port 7861
```

### Issue: Database errors (sqlite3.OperationalError)
**Solution:** Delete the database file and restart:
```bash
rm output/.jobs.db
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860
```

### Issue: Form submission fails with "Could not load HF_TOKEN"
**Solution:** This is expected without Azure secrets. The app logs a warning but doesn't block submission. This will be resolved once you set HF_TOKEN in GitHub Actions.

---

## Next: When to Upgrade to Azure

✅ **Proceed to Pay-As-You-Go when:**
- All "Code Quality" checks pass (black, flake8)
- FastAPI server starts without errors
- UI loads in browser without JS errors
- You've manually tested the resubmit flow in the UI

❌ **Do NOT upgrade if:**
- Linting fails
- API server won't start
- UI has errors in browser console

---

## Phase 2: Azure Testing (30–60 minutes, ~$2–5 cost)

Once Phase 1 is complete and you're confident in the code:

1. **Upgrade Azure subscription** (5 min)
   ```bash
   # Go to https://portal.azure.com → Subscriptions
   # Migrate from $200 credit → Pay-As-You-Go
   ```

2. **Test one small job** ($2–3)
   ```bash
   # Use smallest GPU (T4) and fastest engine (SF3D)
   # Submit via UI → Wait for completion → Verify resubmit works
   ```

3. **Shut down immediately**
   - Delete Container Apps job after testing
   - Cost: Only paid for actual job runtime (~10 min = $2–3)

---

## Quick Command Reference

```bash
# Activate venv
source venv/bin/activate

# Format code (auto-fix)
python -m black .

# Check format (no changes)
python -m black --check .

# Lint check
python -m flake8 --count

# Run tests (skip GPU tests)
python -m pytest tests/ -m "not cuda" -v

# Start API server
python -m uvicorn ui.app:app --host 0.0.0.0 --port 7860 --reload

# Test endpoints (in another terminal)
curl http://localhost:7860/engines | python -m json.tool
curl http://localhost:7860/jobs
```

---

## Questions?

If Phase 1 tests fail, let me know which step failed and I'll help debug before you spend money on Azure.
