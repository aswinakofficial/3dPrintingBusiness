"""Pytest configuration and shared fixtures."""

import pytest
import os
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_directory():
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_data_dir(project_directory):
    """Get or create test data directory."""
    test_data = project_directory / "tests" / "test_data"
    test_data.mkdir(exist_ok=True)
    return test_data


@pytest.fixture(scope="function")
def temp_output_dir(tmp_path):
    """Create temporary output directory for test outputs."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    # Set environment for tests
    os.environ["PYTEST_RUNNING"] = "1"
    # Disable CUDA for most tests to speed up testing
    os.environ["CUDA_VISIBLE_DEVICES"] = ""


# Markers for different test categories
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line("markers", "slow: mark test as slow")
    config.addinivalue_line("markers", "cuda: mark test requires CUDA")
