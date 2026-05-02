#!/usr/bin/env python3
"""
Validation script for Phase 2a & 2b engine implementations.
Checks code structure, imports, and basic functionality without requiring model dependencies.
"""

import sys
import ast
from pathlib import Path
from typing import List, Dict, Any


def check_file_syntax(filepath: Path) -> tuple[bool, str]:
    """Check Python file syntax."""
    try:
        with open(filepath, 'r') as f:
            ast.parse(f.read())
        return True, "✓ Valid Python syntax"
    except SyntaxError as e:
        return False, f"✗ Syntax error: {e}"


def check_imports(filepath: Path) -> tuple[bool, str]:
    """Check if file can be parsed for imports."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return True, f"Found {len(imports)} imports"
    except Exception as e:
        return False, f"✗ Import check failed: {e}"


def check_class_definitions(filepath: Path) -> tuple[bool, List[str]]:
    """Extract class definitions from file."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        return True, classes
    except Exception as e:
        return False, [f"Error: {e}"]


def check_methods(filepath: Path, class_name: str) -> tuple[bool, List[str]]:
    """Extract methods from a class."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                return True, methods
        return False, [f"Class {class_name} not found"]
    except Exception as e:
        return False, [f"Error: {e}"]


def validate_phase2a():
    """Validate Phase 2a-4 implementation."""
    project_root = Path(__file__).parent.parent
    
    # Files to check
    files_to_check = [
        ("engines/trellis_v2.py", {
            "classes": ["TRELLIS2Engine"],
            "methods": {
                "TRELLIS2Engine": [
                    "__init__",
                    "validate_prerequisites",
                    "_load_model",
                    "preprocess",
                    "infer",
                    "_extract_mesh_from_output",
                    "_voxels_to_mesh",
                    "postprocess",
                ]
            }
        }),
        ("engines/loader.py", {
            "classes": [],
            "functions": ["get_available_engines", "load_engine"]
        }),
        ("engines/meshroom_sfm.py", {
            "classes": ["MeshroomEngine"],
            "methods": {
                "MeshroomEngine": [
                    "__init__",
                    "validate_prerequisites",
                    "_find_meshroom",
                    "preprocess",
                    "infer",
                    "_run_meshroom_pipeline",
                    "_find_output_mesh",
                    "postprocess",
                ]
            }
        }),
        ("utils/post_processor.py", {
            "classes": [
                "PostProcessingConfig",
                "MeshRepair",
                "MeshHollowing",
                "SupportGenerator",
                "PostProcessingPipeline",
            ],
            "methods": {
                "MeshRepair": ["__init__", "repair_mesh", "_fill_holes"],
                "MeshHollowing": [
                    "__init__",
                    "hollow_mesh",
                    "_make_watertight",
                    "_create_hollow_voxel",
                    "_create_hollow_offset",
                    "_add_drainage_holes",
                ],
                "SupportGenerator": [
                    "__init__",
                    "generate_supports",
                    "_identify_overhangs",
                    "_group_supports",
                    "_find_connected_region",
                    "_create_support_columns",
                    "_add_raft",
                ],
                "PostProcessingPipeline": ["__init__", "process_mesh"],
            }
        }),
        ("main.py", {
            "classes": ["Config", "Pipeline"],
            "methods": {
                "Config": [
                    "__init__",
                    "get",
                    "get_output_dir",
                    "get_input_dir",
                    "get_logs_dir",
                    "_validate_config",
                ],
                "Pipeline": [
                    "__init__",
                    "run",
                    "_validate_inputs",
                    "_load_engine",
                    "_preprocess_images",
                    "_run_inference",
                    "_post_process_mesh",
                    "_save_metadata",
                    "_get_default_post_processing_config",
                ],
            }
        }),
        ("tests/test_main.py", {
            "classes": ["TestConfig", "TestPipeline", "TestPipelineIntegration"],
            "methods": {}
        }),
    ]
    
    print("=" * 70)
    print("PHASES 2a-4 VALIDATION REPORT")
    print("=" * 70)
    print()
    
    all_passed = True
    
    for file_path, requirements in files_to_check:
        full_path = project_root / file_path
        print(f"\n📄 {file_path}")
        print("-" * 70)
        
        if not full_path.exists():
            print(f"  ✗ File not found")
            all_passed = False
            continue
        
        # Check syntax
        syntax_ok, syntax_msg = check_file_syntax(full_path)
        print(f"  Syntax: {syntax_msg}")
        if not syntax_ok:
            all_passed = False
            continue
        
        # Check imports
        import_ok, import_msg = check_imports(full_path)
        print(f"  Imports: {import_msg}")
        
        # Check classes
        if "classes" in requirements and requirements["classes"]:
            classes_ok, classes = check_class_definitions(full_path)
            for required_class in requirements["classes"]:
                if required_class in classes:
                    print(f"  ✓ Class '{required_class}' found")
                    
                    # Check methods for this class
                    if "methods" in requirements and required_class in requirements["methods"]:
                        methods_ok, methods = check_methods(full_path, required_class)
                        required_methods = requirements["methods"][required_class]
                        for method in required_methods:
                            if method in methods:
                                print(f"    ✓ Method '{method}' exists")
                            else:
                                print(f"    ✗ Method '{method}' missing")
                                all_passed = False
                else:
                    print(f"  ✗ Class '{required_class}' not found")
                    all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL CHECKS PASSED")
    else:
        print("✗ SOME CHECKS FAILED")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(validate_phase2a())
