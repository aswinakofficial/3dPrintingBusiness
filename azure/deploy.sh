#!/bin/bash
# Azure deployment script for 3D Figurine Lab
# Handles infrastructure deployment, configuration, and Docker setup

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEMPLATE_FILE="$SCRIPT_DIR/template.json"
PARAMETERS_FILE="$SCRIPT_DIR/parameters.json"

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

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check Azure CLI
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI not found. Install from https://aka.ms/azure-cli"
        exit 1
    fi
    print_success "Azure CLI installed"
    
    # Check jq for JSON processing
    if ! command -v jq &> /dev/null; then
        print_warning "jq not found. Install for better JSON processing."
    else
        print_success "jq installed"
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_warning "Docker not found. Required for building images."
    else
        print_success "Docker installed"
    fi
    
    echo ""
}

# Authenticate with Azure
authenticate_azure() {
    print_header "Azure Authentication"
    
    print_info "Checking Azure login status..."
    if ! az account show &> /dev/null; then
        print_info "Not logged in. Starting login flow..."
        az login
    fi
    
    # Get subscription info
    SUBSCRIPTION_ID=$(az account show --query id --output tsv)
    SUBSCRIPTION_NAME=$(az account show --query name --output tsv)
    
    print_success "Logged in to subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
    echo ""
}

# Create resource group
create_resource_group() {
    local rg_name=$1
    local location=$2
    
    print_header "Creating Resource Group"
    
    if az group exists --name "$rg_name" | grep -q true; then
        print_info "Resource group '$rg_name' already exists"
    else
        print_info "Creating resource group '$rg_name' in $location..."
        az group create --name "$rg_name" --location "$location"
        print_success "Resource group created"
    fi
    echo ""
}

# Deploy infrastructure
deploy_infrastructure() {
    local rg_name=$1
    local deployment_name=$2
    
    print_header "Deploying Infrastructure"
    
    print_info "Validating ARM template..."
    az deployment group validate \
        --resource-group "$rg_name" \
        --template-file "$TEMPLATE_FILE" \
        --parameters "$PARAMETERS_FILE"
    print_success "Template validation passed"
    
    print_info "Deploying resources (this may take 10-15 minutes)..."
    DEPLOYMENT=$(az deployment group create \
        --name "$deployment_name" \
        --resource-group "$rg_name" \
        --template-file "$TEMPLATE_FILE" \
        --parameters "$PARAMETERS_FILE" \
        --output json)
    
    print_success "Infrastructure deployed"
    echo ""
    
    # Extract outputs
    STORAGE_ACCOUNT=$(echo "$DEPLOYMENT" | jq -r '.properties.outputs.storageAccountName.value')
    ACR_NAME=$(echo "$DEPLOYMENT" | jq -r '.properties.outputs.containerRegistryName.value')
    ACR_URL=$(echo "$DEPLOYMENT" | jq -r '.properties.outputs.containerRegistryUrl.value')
    KV_NAME=$(echo "$DEPLOYMENT" | jq -r '.properties.outputs.keyVaultName.value')
    
    echo "Storage Account: $STORAGE_ACCOUNT"
    echo "Container Registry: $ACR_NAME"
    echo "Container Registry URL: $ACR_URL"
    echo "Key Vault: $KV_NAME"
    echo ""
}

# Build and push Docker images
build_and_push_images() {
    local acr_name=$1
    local acr_url=$2
    
    print_header "Building and Pushing Docker Images"
    
    # Login to ACR
    print_info "Logging in to Azure Container Registry..."
    az acr login --name "$acr_name"
    print_success "Logged in to ACR"
    
    # Build TRELLIS.2 image
    print_info "Building TRELLIS.2 image..."
    cd "$PROJECT_DIR"
    docker build -f docker/Dockerfile.trellis -t "$acr_url/3dfigurine-trellis:latest" .
    print_success "TRELLIS.2 image built"
    
    # Build Meshroom image
    print_info "Building Meshroom image..."
    docker build -f docker/Dockerfile.meshroom -t "$acr_url/3dfigurine-meshroom:latest" .
    print_success "Meshroom image built"
    
    # Push images
    print_info "Pushing TRELLIS.2 image to ACR..."
    docker push "$acr_url/3dfigurine-trellis:latest"
    print_success "TRELLIS.2 image pushed"
    
    print_info "Pushing Meshroom image to ACR..."
    docker push "$acr_url/3dfigurine-meshroom:latest"
    print_success "Meshroom image pushed"
    
    echo ""
}

# Configure VM
configure_vm() {
    local rg_name=$1
    local vm_name=$2
    
    print_header "Configuring Virtual Machine"
    
    # Run custom script
    print_info "Running VM configuration script..."
    az vm run-command invoke \
        --resource-group "$rg_name" \
        --name "$vm_name" \
        --command-id RunShellScript \
        --scripts @"$SCRIPT_DIR/vm-setup.sh" \
        --output json | jq '.value[0].message'
    
    print_success "VM configuration complete"
    echo ""
}

# Setup monitoring
setup_monitoring() {
    local rg_name=$1
    
    print_header "Setting up Monitoring"
    
    # Create action group for alerts
    print_info "Creating action group for alerts..."
    az monitor action-group create \
        --resource-group "$rg_name" \
        --name "3dfigurine-alerts" \
        --short-name "3dfig" || print_warning "Action group may already exist"
    
    print_success "Monitoring configured"
    echo ""
}

# Display deployment summary
display_summary() {
    local rg_name=$1
    
    print_header "Deployment Summary"
    
    echo "Resource Group: $rg_name"
    echo "Region: $(az group show --name "$rg_name" --query location --output tsv)"
    echo ""
    
    print_info "Resources deployed:"
    az resource list --resource-group "$rg_name" --query "[].{Name:name, Type:type}" --output table
    echo ""
    
    print_success "Deployment complete!"
    print_info "Next steps:"
    echo "1. Access the VM with SSH key configured in Key Vault"
    echo "2. Pull and run Docker containers from ACR"
    echo "3. View logs in Application Insights"
    echo "4. Monitor resource usage and costs"
    echo ""
}

# Main deployment
main() {
    if [ $# -lt 1 ]; then
        echo "Usage: $0 <resource-group-name> [resource-location]"
        echo ""
        echo "Examples:"
        echo "  $0 3dfigurine-rg eastus"
        echo "  $0 3dfigurine-prod eastus2"
        echo ""
        exit 1
    fi
    
    local rg_name=$1
    local location=${2:-eastus}
    local deployment_name="3dfigurine-deployment-$(date +%s)"
    local vm_name="3dfigurine-prod-vm"
    
    # Execute deployment steps
    check_prerequisites
    authenticate_azure
    create_resource_group "$rg_name" "$location"
    deploy_infrastructure "$rg_name" "$deployment_name"
    
    # Ask about building images
    read -p "Build and push Docker images? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        build_and_push_images "$ACR_NAME" "${ACR_URL#https://}"
    fi
    
    # Configure VM
    read -p "Configure VM with Docker? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        configure_vm "$rg_name" "$vm_name"
    fi
    
    # Setup monitoring
    setup_monitoring "$rg_name"
    
    # Display summary
    display_summary "$rg_name"
}

# Run main
main "$@"
