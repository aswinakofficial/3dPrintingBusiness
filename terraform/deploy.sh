#!/bin/bash
# Terraform Deployment Script for 3D Figurine Lab
# Provides interactive guided deployment with Terraform

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TERRAFORM_DIR="$SCRIPT_DIR/terraform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "=========================================="
echo "3D Figurine Lab - Terraform Deployment"
echo "==========================================${NC}"
echo ""

# Function to print messages
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if ! command -v terraform &> /dev/null; then
    print_error "Terraform not found. Install it first:"
    echo "  https://learn.hashicorp.com/tutorials/terraform/install-cli"
    exit 1
fi
print_status "Terraform $(terraform version -json | jq -r '.terraform_version')"

if ! command -v az &> /dev/null; then
    print_error "Azure CLI not found. Install it first:"
    echo "  curl -sL https://aka.ms/InstallAzureCLIDeb | bash"
    exit 1
fi
print_status "Azure CLI $(az version -o json | jq -r '.["azure-cli"]')"

# Authenticate with Azure
echo ""
echo -e "${BLUE}Authenticating with Azure...${NC}"

ACCOUNT=$(az account show 2>/dev/null || echo "")
if [ -z "$ACCOUNT" ]; then
    print_info "Please login to Azure:"
    az login
else
    ACCOUNT_NAME=$(echo "$ACCOUNT" | jq -r '.name')
    print_status "Already authenticated as: $ACCOUNT_NAME"
fi

# Select subscription
SUBSCRIPTION=$(az account show -o json | jq -r '.id')
print_status "Using subscription: $SUBSCRIPTION"

# Initialize Terraform
echo ""
echo -e "${BLUE}Initializing Terraform...${NC}"

cd "$TERRAFORM_DIR"

if [ ! -d ".terraform" ]; then
    print_info "Running terraform init..."
    terraform init
    print_status "Terraform initialized"
else
    print_status "Terraform already initialized"
fi

# Select environment
echo ""
echo -e "${BLUE}Select deployment environment:${NC}"
echo "  1) Development (dev.tfvars)"
echo "  2) Staging (staging.tfvars)"
echo "  3) Production (terraform.tfvars)"
read -p "Enter choice [1-3]: " env_choice

case $env_choice in
    1)
        TFVARS_FILE="dev.tfvars"
        ENV="Development"
        ;;
    2)
        TFVARS_FILE="staging.tfvars"
        ENV="Staging"
        ;;
    3)
        TFVARS_FILE="terraform.tfvars"
        ENV="Production"
        ;;
    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

print_status "Selected environment: $ENV ($TFVARS_FILE)"

# Review and modify variables (optional)
echo ""
read -p "Do you want to modify any variables? (y/n): " modify_vars
if [ "$modify_vars" = "y" ]; then
    print_info "Edit $TFVARS_FILE in your editor"
    read -p "Press Enter when done..."
fi

# Plan deployment
echo ""
echo -e "${BLUE}Planning Terraform deployment...${NC}"
print_info "This shows what will be created/modified/deleted"

terraform plan -var-file="$TFVARS_FILE" -out="tfplan"

# Confirm deployment
echo ""
echo -e "${YELLOW}Review the plan above carefully${NC}"
read -p "Do you want to proceed with deployment? (type 'yes' to confirm): " confirm

if [ "$confirm" != "yes" ]; then
    print_error "Deployment cancelled"
    rm -f tfplan
    exit 0
fi

# Apply deployment
echo ""
echo -e "${BLUE}Applying Terraform configuration...${NC}"
print_warning "This will create Azure resources (costs will accrue)"

terraform apply tfplan

# Get outputs
echo ""
echo -e "${GREEN}Deployment successful!${NC}"
echo ""
echo -e "${BLUE}=== Deployment Summary ===${NC}"
terraform output deployment_summary

echo ""
echo -e "${BLUE}=== Connection Details ===${NC}"
echo -e "${GREEN}SSH Command:${NC}"
terraform output -raw vm_ssh_command
echo ""

echo -e "${BLUE}=== Next Steps ===${NC}"
echo "1. Wait 2-3 minutes for VM to fully initialize"
echo "2. Connect via SSH:"
terraform output -raw vm_ssh_command
echo ""
echo "3. Verify Docker installation:"
echo "   docker --version"
echo "   docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi"
echo ""
echo "4. Pull container images from ACR:"
ACR=$(terraform output -raw container_registry_login_server)
echo "   docker pull $ACR/3dfigurine-trellis:latest"
echo "   docker pull $ACR/3dfigurine-meshroom:latest"
echo ""
echo "5. Start processing with docker-compose"
echo ""

# Cleanup plan file
rm -f tfplan

print_status "Deployment complete"
print_info "Store these outputs safely. Use 'terraform output' to retrieve anytime"

# Optional: Show cost estimation
echo ""
read -p "Do you want to estimate monthly costs? (y/n): " estimate_costs
if [ "$estimate_costs" = "y" ]; then
    print_info "Monthly cost estimation:"
    echo "  VM (A100 GPU): ~\$4,500-5,500"
    echo "  Storage (Premium LRS): ~\$150-200"
    echo "  Container Registry: ~\$200"
    echo "  Monitoring: ~\$50-150"
    echo "  ───────────────────────"
    echo "  TOTAL: ~\$4,900-6,050/month"
    echo ""
    echo "  Optimization options:"
    echo "  - Use Spot VMs: save 70-80% (~\$1,000-1,500/month)"
    echo "  - Scale down to V100: save ~50% (~\$2,500/month)"
    echo "  - Enable scheduled shutdown: save ~40% (~\$2,000/month)"
fi

cd - > /dev/null
