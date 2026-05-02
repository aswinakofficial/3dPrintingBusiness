#!/bin/bash
# Docker build and management script for 3D Figurine Lab
# Handles building, tagging, and pushing Docker images

set -e

# Configuration
REGISTRY="${DOCKER_REGISTRY:-3dfigurine}"
VERSION="${VERSION:-latest}"
TRELLIS_IMAGE="${REGISTRY}-trellis:${VERSION}"
MESHROOM_IMAGE="${REGISTRY}-meshroom:${VERSION}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Functions
print_header() {
    echo -e "${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Main script
if [ $# -eq 0 ]; then
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  build             Build all Docker images"
    echo "  build-trellis     Build TRELLIS.2 image only"
    echo "  build-meshroom    Build Meshroom image only"
    echo "  list              List all available images"
    echo "  push              Push images to registry"
    echo "  clean             Remove all Docker images"
    echo "  test-trellis      Run TRELLIS.2 container test"
    echo "  test-meshroom     Run Meshroom container test"
    echo ""
    exit 1
fi

case "$1" in
    build)
        print_header "Building all 3D Figurine Lab Docker images"
        echo "Building TRELLIS.2 image: $TRELLIS_IMAGE"
        docker build -f docker/Dockerfile.trellis -t "$TRELLIS_IMAGE" .
        print_success "TRELLIS.2 image built"
        
        echo ""
        echo "Building Meshroom image: $MESHROOM_IMAGE"
        docker build -f docker/Dockerfile.meshroom -t "$MESHROOM_IMAGE" .
        print_success "Meshroom image built"
        
        echo ""
        print_success "All images built successfully"
        docker images | grep 3dfigurine
        ;;
        
    build-trellis)
        print_header "Building TRELLIS.2 Docker image"
        docker build -f docker/Dockerfile.trellis -t "$TRELLIS_IMAGE" .
        print_success "TRELLIS.2 image built: $TRELLIS_IMAGE"
        ;;
        
    build-meshroom)
        print_header "Building Meshroom Docker image"
        docker build -f docker/Dockerfile.meshroom -t "$MESHROOM_IMAGE" .
        print_success "Meshroom image built: $MESHROOM_IMAGE"
        ;;
        
    list)
        print_header "3D Figurine Lab Docker images"
        docker images | grep -E "3dfigurine|REPOSITORY" || echo "No 3dfigurine images found"
        ;;
        
    push)
        print_header "Pushing images to registry"
        print_warning "Ensure Docker is configured for your registry"
        docker push "$TRELLIS_IMAGE"
        print_success "TRELLIS.2 image pushed"
        docker push "$MESHROOM_IMAGE"
        print_success "Meshroom image pushed"
        ;;
        
    clean)
        print_header "Cleaning up Docker images"
        docker rmi "$TRELLIS_IMAGE" || print_warning "Could not remove $TRELLIS_IMAGE"
        docker rmi "$MESHROOM_IMAGE" || print_warning "Could not remove $MESHROOM_IMAGE"
        print_success "Cleanup complete"
        ;;
        
    test-trellis)
        print_header "Testing TRELLIS.2 container"
        mkdir -p input output logs
        docker run --rm \
            --gpus all \
            -v "$(pwd)/input:/app/input" \
            -v "$(pwd)/output:/app/output" \
            -v "$(pwd)/logs:/app/logs" \
            "$TRELLIS_IMAGE" \
            python main.py --help
        print_success "TRELLIS.2 container test passed"
        ;;
        
    test-meshroom)
        print_header "Testing Meshroom container"
        mkdir -p input output logs
        docker run --rm \
            --gpus all \
            -v "$(pwd)/input:/app/input" \
            -v "$(pwd)/output:/app/output" \
            -v "$(pwd)/logs:/app/logs" \
            "$MESHROOM_IMAGE" \
            python main.py --help
        print_success "Meshroom container test passed"
        ;;
        
    *)
        print_error "Unknown command: $1"
        exit 1
        ;;
esac
