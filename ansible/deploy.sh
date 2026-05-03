#!/bin/bash

###############################################################################
# Ansible Deployment Script for 3D Figurine Lab
# 
# Provides interactive deployment of VM configuration using Ansible
# Simplifies common deployment tasks and validates prerequisites
###############################################################################

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_FILE="$SCRIPT_DIR/inventory/hosts"
PLAYBOOK_FILE="$SCRIPT_DIR/playbooks/deploy.yml"
ANSIBLE_LOG="$SCRIPT_DIR/ansible-deploy.log"

###############################################################################
# Utility Functions
###############################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_banner() {
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   3D Figurine Lab - Ansible Deployment                        ║${NC}"
    echo -e "${BLUE}║   Infrastructure Configuration & Setup                        ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
}

print_menu() {
    echo -e "\n${BLUE}Deployment Options:${NC}"
    echo "1. Full deployment (all roles)"
    echo "2. Docker & NVIDIA setup only"
    echo "3. Application setup only"
    echo "4. Monitoring setup only"
    echo "5. Validate playbook syntax"
    echo "6. Test SSH connection"
    echo "7. Show configuration (dry-run)"
    echo "8. Exit"
    echo ""
}

###############################################################################
# Prerequisite Checks
###############################################################################

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if ansible is installed
    if ! command -v ansible-playbook &> /dev/null; then
        log_error "Ansible not found. Install with: pip install ansible>=2.10"
        exit 1
    fi
    log_success "Ansible found: $(ansible-playbook --version | head -1)"
    
    # Check if SSH key exists
    if [ ! -f "$HOME/.ssh/azure_3dfigurine" ]; then
        log_warning "SSH key not found at ~/.ssh/azure_3dfigurine"
        log_info "Create it with: ssh-keygen -t rsa -b 4096 -f ~/.ssh/azure_3dfigurine"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_success "SSH key found"
    fi
    
    # Check if inventory file exists
    if [ ! -f "$INVENTORY_FILE" ]; then
        log_error "Inventory file not found: $INVENTORY_FILE"
        exit 1
    fi
    log_success "Inventory file found"
    
    # Check if playbook file exists
    if [ ! -f "$PLAYBOOK_FILE" ]; then
        log_error "Playbook file not found: $PLAYBOOK_FILE"
        exit 1
    fi
    log_success "Playbook file found"
}

###############################################################################
# Environment Selection
###############################################################################

select_environment() {
    echo -e "\n${BLUE}Select target environment:${NC}"
    echo "1. prod    (Production A100 GPUs, 80GB memory)"
    echo "2. staging (Staging A100 GPUs, 60GB memory)"
    echo "3. dev     (Development single GPU, 40GB memory)"
    echo "4. all     (All environments)"
    read -p "Choice [1-4] (default: 1): " env_choice
    env_choice=${env_choice:-1}
    
    case $env_choice in
        1) TARGET_ENV="prod" ;;
        2) TARGET_ENV="staging" ;;
        3) TARGET_ENV="dev" ;;
        4) TARGET_ENV="all" ;;
        *) log_error "Invalid choice"; select_environment ;;
    esac
    
    if [ "$TARGET_ENV" = "all" ]; then
        LIMIT_ARG=""
        log_info "Target: All environments (prod, staging, dev)"
    else
        LIMIT_ARG="-l $TARGET_ENV"
        log_info "Target: $TARGET_ENV environment"
    fi
}

###############################################################################
# Configuration Updates
###############################################################################

update_inventory() {
    if [ "$TARGET_ENV" = "all" ] || [ "$TARGET_ENV" = "prod" ]; then
        read -p "Enter PROD VM IP [skip to keep current]: " prod_ip
        if [ ! -z "$prod_ip" ]; then
            sed -i.bak "s/<PROD_IP>/$prod_ip/" "$INVENTORY_FILE"
            log_success "Updated PROD IP to $prod_ip"
        fi
    fi
    
    if [ "$TARGET_ENV" = "all" ] || [ "$TARGET_ENV" = "staging" ]; then
        read -p "Enter STAGING VM IP [skip to keep current]: " staging_ip
        if [ ! -z "$staging_ip" ]; then
            sed -i.bak "s/<STAGING_IP>/$staging_ip/" "$INVENTORY_FILE"
            log_success "Updated STAGING IP to $staging_ip"
        fi
    fi
    
    if [ "$TARGET_ENV" = "all" ] || [ "$TARGET_ENV" = "dev" ]; then
        read -p "Enter DEV VM IP [skip to keep current]: " dev_ip
        if [ ! -z "$dev_ip" ]; then
            sed -i.bak "s/<DEV_IP>/$dev_ip/" "$INVENTORY_FILE"
            log_success "Updated DEV IP to $dev_ip"
        fi
    fi
}

###############################################################################
# Deployment Actions
###############################################################################

check_ssh_connectivity() {
    log_info "Testing SSH connectivity..."
    
    if ansible all -i "$INVENTORY_FILE" $LIMIT_ARG -m ping --one-line 2>/dev/null; then
        log_success "SSH connectivity verified"
        return 0
    else
        log_error "SSH connectivity failed"
        log_info "Troubleshooting tips:"
        log_info "  1. Check inventory IPs in: $INVENTORY_FILE"
        log_info "  2. Verify SSH key permissions: chmod 600 ~/.ssh/azure_3dfigurine"
        log_info "  3. Test manually: ssh -i ~/.ssh/azure_3dfigurine azureuser@<IP>"
        return 1
    fi
}

validate_syntax() {
    log_info "Validating playbook syntax..."
    ansible-playbook -i "$INVENTORY_FILE" "$PLAYBOOK_FILE" --syntax-check
    log_success "Playbook syntax is valid"
}

dry_run() {
    log_info "Running playbook in check mode (dry-run)..."
    ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" --check --diff
}

deploy_full() {
    select_environment
    log_info "Starting full deployment..."
    log_info "Roles will be deployed in sequence:"
    log_info "  1. docker-install"
    log_info "  2. nvidia-docker"
    log_info "  3. application"
    log_info "  4. monitoring"
    echo ""
    read -p "Continue with deployment? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warning "Deployment cancelled"
        return
    fi
    
    log_info "Deployment starting at $(date)"
    ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" 2>&1 | tee -a "$ANSIBLE_LOG"
    
    if [ $? -eq 0 ]; then
        log_success "Deployment completed successfully"
        echo ""
        echo -e "${BLUE}Next steps:${NC}"
        echo "1. Verify services: systemctl status 3dfigurine-trellis"
        echo "2. Check logs: journalctl -u 3dfigurine-trellis -f"
        echo "3. Run health check: /usr/local/bin/3dfigurine-healthcheck"
        echo "4. View metrics: /usr/local/bin/3dfigurine-monitor"
    else
        log_error "Deployment failed. Check log: $ANSIBLE_LOG"
        exit 1
    fi
}

deploy_infrastructure() {
    select_environment
    log_info "Deploying infrastructure (docker, NVIDIA Docker)..."
    ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" \
        --tags docker,nvidia-docker 2>&1 | tee -a "$ANSIBLE_LOG"
}

deploy_application() {
    select_environment
    log_info "Deploying application configuration..."
    ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" \
        --tags application 2>&1 | tee -a "$ANSIBLE_LOG"
}

deploy_monitoring() {
    select_environment
    log_info "Deploying monitoring setup..."
    ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" \
        --tags monitoring 2>&1 | tee -a "$ANSIBLE_LOG"
}

###############################################################################
# Advanced Options
###############################################################################

show_inventory() {
    log_info "Current Inventory Configuration:"
    echo ""
    ansible-inventory -i "$INVENTORY_FILE" --list 2>/dev/null || cat "$INVENTORY_FILE"
}

show_variables() {
    log_info "Variables for selected environment:"
    select_environment
    ansible-inventory -i "$INVENTORY_FILE" $LIMIT_ARG --host $(ansible-inventory -i "$INVENTORY_FILE" $LIMIT_ARG --list 2>/dev/null | grep -o '"[^"]*"' | head -1 | tr -d '"') 2>/dev/null || echo "Unable to retrieve variables"
}

view_logs() {
    if [ -f "$ANSIBLE_LOG" ]; then
        log_info "Recent deployment log:"
        tail -50 "$ANSIBLE_LOG"
    else
        log_warning "No deployment log found yet"
    fi
}

###############################################################################
# Interactive Menu
###############################################################################

interactive_menu() {
    while true; do
        print_menu
        read -p "Select option [1-8]: " menu_choice
        
        case $menu_choice in
            1)
                deploy_full
                ;;
            2)
                select_environment
                log_info "Deploying Docker & NVIDIA Docker..."
                ansible-playbook -i "$INVENTORY_FILE" $LIMIT_ARG "$PLAYBOOK_FILE" \
                    --tags docker,nvidia-docker
                ;;
            3)
                deploy_application
                ;;
            4)
                deploy_monitoring
                ;;
            5)
                validate_syntax
                ;;
            6)
                select_environment
                check_ssh_connectivity
                ;;
            7)
                select_environment
                dry_run
                ;;
            8)
                log_info "Exiting..."
                exit 0
                ;;
            *)
                log_error "Invalid option"
                ;;
        esac
    done
}

###############################################################################
# Main Entry Point
###############################################################################

main() {
    print_banner
    
    # Check prerequisites
    check_prerequisites
    log_success "All prerequisites satisfied\n"
    
    # Parse command line arguments
    if [ $# -eq 0 ]; then
        # Interactive mode
        interactive_menu
    else
        # Command mode
        case "$1" in
            deploy)
                deploy_full
                ;;
            deploy:infra)
                deploy_infrastructure
                ;;
            deploy:app)
                deploy_application
                ;;
            deploy:monitoring)
                deploy_monitoring
                ;;
            validate)
                validate_syntax
                ;;
            test)
                select_environment
                check_ssh_connectivity
                ;;
            dryrun)
                select_environment
                dry_run
                ;;
            status)
                show_inventory
                ;;
            logs)
                view_logs
                ;;
            help)
                echo "Usage: $0 [COMMAND]"
                echo ""
                echo "Commands:"
                echo "  deploy           Full deployment (interactive)"
                echo "  deploy:infra     Docker & NVIDIA Docker only"
                echo "  deploy:app       Application configuration only"
                echo "  deploy:monitoring Monitoring setup only"
                echo "  validate         Syntax validation"
                echo "  test             Test SSH connectivity"
                echo "  dryrun           Dry-run preview changes"
                echo "  status           Show inventory status"
                echo "  logs             View deployment logs"
                echo "  help             Show this message"
                echo ""
                echo "Run without arguments for interactive menu"
                ;;
            *)
                log_error "Unknown command: $1"
                echo "Use: $0 help"
                exit 1
                ;;
        esac
    fi
}

# Run main function
main "$@"
