#!/bin/bash
# Terraform deployment helper for 3D Figurine Lab shared Azure infrastructure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

print_status() {
    printf '[OK] %s\n' "$1"
}

print_info() {
    printf '[INFO] %s\n' "$1"
}

print_warn() {
    printf '[WARN] %s\n' "$1"
}

print_error() {
    printf '[ERROR] %s\n' "$1" >&2
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Missing required command: $1"
        exit 1
    fi
}

echo "=========================================="
echo "3D Figurine Lab - Terraform Deployment"
echo "=========================================="
echo ""

require_command terraform
require_command az

if command -v jq >/dev/null 2>&1; then
    print_status "Terraform $(terraform version -json | jq -r '.terraform_version')"
    print_status "Azure CLI $(az version -o json | jq -r '.[\"azure-cli\"]')"
else
    print_status "Terraform is installed"
    print_status "Azure CLI is installed"
fi

ACCOUNT_JSON="$(az account show 2>/dev/null || true)"
if [ -z "$ACCOUNT_JSON" ]; then
    print_info "Azure CLI is not authenticated. Starting az login..."
    az login
    ACCOUNT_JSON="$(az account show -o json)"
fi

if command -v jq >/dev/null 2>&1; then
    ACCOUNT_NAME="$(printf '%s' "$ACCOUNT_JSON" | jq -r '.name')"
    SUBSCRIPTION_ID="$(printf '%s' "$ACCOUNT_JSON" | jq -r '.id')"
else
    ACCOUNT_NAME="$(az account show --query name -o tsv)"
    SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
fi

print_status "Authenticated subscription: $SUBSCRIPTION_ID"
print_status "Subscription name: $ACCOUNT_NAME"

cd "$SCRIPT_DIR"

if [ ! -d ".terraform" ]; then
    print_info "Running terraform init..."
    terraform init
else
    print_status "Terraform already initialized"
fi

echo ""
echo "Select deployment environment:"
echo "  1) Development (dev.tfvars)"
echo "  2) Staging (staging.tfvars)"
echo "  3) Production (terraform.tfvars)"
read -r -p "Enter choice [1-3]: " env_choice

case "$env_choice" in
    1)
        TFVARS_FILE="dev.tfvars"
        ENV_NAME="development"
        ;;
    2)
        TFVARS_FILE="staging.tfvars"
        ENV_NAME="staging"
        ;;
    3)
        TFVARS_FILE="terraform.tfvars"
        ENV_NAME="production"
        ;;
    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

print_status "Selected environment: $ENV_NAME"
print_info "Planning with $TFVARS_FILE"

terraform plan -var-file="$TFVARS_FILE" -out="tfplan"

echo ""
read -r -p "Apply this Terraform plan? Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
    print_warn "Deployment cancelled"
    rm -f tfplan
    exit 0
fi

terraform apply tfplan

echo ""
print_status "Deployment successful"
print_info "Deployment summary:"
terraform output deployment_summary

RESOURCE_GROUP="$(terraform output -raw resource_group_name)"
ACR_LOGIN_SERVER="$(terraform output -raw container_registry_login_server)"
ACR_NAME="$(terraform output -raw container_registry_name)"

echo ""
echo "Next steps:"
echo "1. Build and push images from the repository root:"
echo "   cd $REPO_ROOT"
echo "   docker build -f docker/Dockerfile.meshroom -t 3dfigurine-meshroom:latest ."
echo "   az acr build --registry $ACR_NAME --image 3dfigurine-meshroom:latest -f docker/Dockerfile.meshroom ."
echo "   docker build -f docker/Dockerfile.trellis -t 3dfigurine-trellis:latest ."
echo "   az acr build --registry $ACR_NAME --image 3dfigurine-trellis:latest -f docker/Dockerfile.trellis ."
echo "2. Submit ACI jobs from the repository root:"
echo "   python3 scripts/aci_job_runner.py --job-type meshroom --input-dir /path/to/images"
echo "3. Verify running jobs:"
echo "   az container list --resource-group $RESOURCE_GROUP --output table"
echo "4. Use the ACR login server in runtime configuration if needed:"
echo "   $ACR_LOGIN_SERVER"

rm -f tfplan
print_status "Done"
