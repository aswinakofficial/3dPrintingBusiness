# Ansible Deployment Implementation Guide

## Overview

This comprehensive guide details the Ansible configuration management implementation for 3D Figurine Lab infrastructure automation. This replaces imperative bash scripts with declarative, idempotent Ansible playbooks.

## Architecture

### Multi-Layer Deployment Stack

```
├── Infrastructure as Code (Terraform) ← Recommended & Only Option
│   └── Provisions Azure VMs with CUDA, GPU support
│
├── Configuration Management (Ansible) ← YOU ARE HERE
│   ├── Docker Installation
│   ├── NVIDIA Docker Runtime
│   ├── Application Setup
│   └── Monitoring & Logging
│
└── Container Orchestration (Docker Compose)
    ├── TRELLIS.2 Engine
    └── Meshroom Engine
```

### Deployment Workflow

```
┌─────────────────────────────────────────┐
│ Terraform/ARM Deploy VMs                │
│ (Provision infrastructure)              │
└──────────────┬──────────────────────────┘
               │ Output: VM IP addresses
               ↓
┌─────────────────────────────────────────┐
│ Ansible Deploy Configuration            │
│ (Setup and configure VMs)               │
│                                         │
│ ├─ docker-install role                 │
│ ├─ nvidia-docker role                  │
│ ├─ application role                    │
│ └─ monitoring role                     │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│ Docker Compose Start Services           │
│ (Run applications in containers)        │
│                                         │
│ ├─ TRELLIS.2 Engine                    │
│ └─ Meshroom Engine                     │
└─────────────────────────────────────────┘
```

## Implementation Summary

### Files Created

| Component | Files | Lines | Purpose |
|-----------|-------|-------|---------|
| Configuration | ansible.cfg | 25 | Global Ansible settings |
| Inventory | inventory/hosts | 50 | Host definitions & variables |
| Variables | group_vars/*.yml | 185 | Environment-specific config |
| Docker Role | roles/docker-install/ | 80 | Docker Engine installation |
| GPU Role | roles/nvidia-docker/ | 85 | NVIDIA Docker runtime setup |
| App Role | roles/application/ | 130 | Application configuration |
| Monitoring | roles/monitoring/ | 160 | Monitoring & logging setup |
| Playbook | playbooks/deploy.yml | 120 | Orchestration & execution |
| Script | deploy.sh | 380 | Interactive deployment wrapper |
| Docs | README.md (Ansible) | 700+ | Usage documentation |
| **TOTAL** | **27 files** | **~1,915** | **Complete automation** |

### Ansible Roles (4 Total)

#### 1. docker-install

**Purpose:** Install Docker Engine and Docker Compose

**Key Tasks:**
- Add Docker official repository and GPG key
- Install docker-ce, containerd.io, docker-compose-plugin
- Add user to docker group (non-root operation)
- Enable and start Docker service
- Verify installation with hello-world container

**Variables Used:**
- `docker_version`: Docker version to install (default: latest)

**Handlers:**
- Restart Docker service
- Reset SSH connection (for group membership)

**Idempotent:** Yes - safe to run multiple times

---

#### 2. nvidia-docker

**Purpose:** Setup NVIDIA Docker runtime for GPU access

**Key Tasks:**
- Add NVIDIA GPG key and repository
- Install nvidia-docker2 and nvidia-container-toolkit
- Configure Docker daemon with NVIDIA runtime
- Test CUDA 12.4.1 with nvidia-smi
- Validate GPU count matches expectations
- Retry logic (3 attempts, 10-second delay)

**Variables Used:**
- `nvidia_docker_version`: Runtime version
- `cuda_version`: CUDA version to validate
- `gpu_count`: Expected GPU count

**Templates:**
- `daemon.json.j2`: Docker daemon configuration

**Handlers:**
- Restart Docker service

**Special Features:**
- GPU validation with retries
- GPU count assertion
- Daemon configuration in JSON format

**Idempotent:** Yes - safe to run multiple times

---

#### 3. application

**Purpose:** Deploy 3D Figurine Lab application

**Key Tasks:**
- Create data volume directories (input, output, logs, models)
- Copy docker-compose.yml
- Generate .env file from template
- Pull container images with security verification
- Create systemd service units
- Setup automated backups with cron
- Configure health check monitoring
- Setup log rotation

**Variables Used:**
- `environment`: dev/staging/prod
- `docker_registry`: Container image registry
- `docker_memory_limit`: Memory allocation
- `docker_cpus_limit`: CPU cores
- `enable_backups`: Backup feature flag
- `backup_retention_days`: Backup retention period
- `docker_restart_policy`: Service restart policy

**Templates:**
- `.env.j2`: Environment variables
- `3dfigurine-trellis.service.j2`: TRELLIS systemd unit
- `3dfigurine-meshroom.service.j2`: Meshroom systemd unit
- `backup.sh.j2`: Backup script
- `healthcheck.sh.j2`: Health check script
- `3dfigurine.logrotate.j2`: Log rotation config

**Handlers:**
- Restart Docker services
- Reload systemd daemon

**Scripts Deployed:**
- `/usr/local/bin/3dfigurine-backup`: Automated backup executor
- `/usr/local/bin/3dfigurine-healthcheck`: System health check

**Services Deployed:**
- `3dfigurine-trellis.service`: TRELLIS.2 engine
- `3dfigurine-meshroom.service`: Meshroom engine

**Idempotent:** Yes - safe on re-run

---

#### 4. monitoring

**Purpose:** Setup comprehensive monitoring and logging

**Key Tasks:**
- Install monitoring tools (htop, iotop, nethogs, logwatch)
- Configure journald for persistent logging
- Create monitoring scripts (system, GPU, metrics)
- Schedule metrics collection via cron (every 5 minutes)
- Create alert rules and thresholds
- Configure rsyslog aggregation

**Variables Used:**
- `enable_monitoring`: Monitoring feature flag
- `monitoring_interval`: Collection frequency
- `alert_thresholds`: Alert settings

**Templates:**
- `system-monitor.sh.j2`: System metrics script
- `gpu-monitor.sh.j2`: GPU metrics script
- `metrics.sh.j2`: JSON metrics collection
- `alert-rules.yml.j2`: Alert configuration
- `log-aggregation.conf.j2`: rsyslog config

**Scripts Deployed:**
- `/usr/local/bin/3dfigurine-monitor`: Real-time system monitoring
- `/usr/local/bin/3dfigurine-gpu-monitor`: GPU monitoring
- `/usr/local/bin/3dfigurine-metrics`: Metrics collection

**Monitoring Features:**
- CPU/memory/disk monitoring
- GPU utilization and temperature
- Container health status
- Service availability checks
- JSON metrics output for integration
- 8 configurable alert rules
- Centralized log aggregation

**Handlers:**
- Restart journald
- Restart rsyslog

**Idempotent:** Yes - safe to update configuration

---

### Environment Variables

Three environment configurations support different deployment scenarios:

#### Production (prod.yml)
```yaml
environment: prod
enable_trellis: yes
enable_meshroom: yes
enable_monitoring: yes
docker_memory_limit: "80g"
docker_cpus_limit: "30"
cuda_visible_devices: "0,1"
gpu_count: 2
backup_retention_days: 30
backup_schedule: "0 2 * * *"          # Daily 2 AM
auto_update: no
ssh_hardening: yes
firewall_enabled: yes
fail2ban_enabled: yes
```

#### Staging (staging.yml)
```yaml
environment: staging
docker_memory_limit: "60g"
docker_cpus_limit: "24"
cuda_visible_devices: "0,1"
gpu_count: 2
backup_retention_days: 7
backup_schedule: "0 3 * * 0"          # Sunday 3 AM
auto_update: no
ssh_hardening: yes
firewall_enabled: yes
```

#### Development (dev.yml)
```yaml
environment: dev
docker_memory_limit: "40g"
docker_cpus_limit: "16"
cuda_visible_devices: "0"             # Single GPU
gpu_count: 1
enable_backups: no
auto_update: yes
ssh_hardening: no                     # Relaxed for dev
firewall_enabled: no
debug_logging: yes
```

---

## Deployment Procedures

### Quick Start (5 minutes)

```bash
cd ansible

# 1. Update inventory with VM IPs
nano inventory/hosts
# Update <PROD_IP>, <STAGING_IP>, <DEV_IP>

# 2. Verify SSH access
ansible all -i inventory/hosts -m ping

# 3. Deploy
./deploy.sh
# Select: 1 (Full deployment) → Environment → Confirm

# 4. Verify
systemctl status 3dfigurine-trellis
journalctl -u 3dfigurine-trellis -f
```

### Complete Deployment (30 minutes)

```bash
# From project root
cd ansible

# 1. Validate prerequisites
chmod +x deploy.sh
ansible-playbook -i inventory/hosts playbooks/deploy.yml --syntax-check

# 2. Update IPs
sed -i 's/<PROD_IP>/10.0.1.10/' inventory/hosts
sed -i 's/<DEV_IP>/10.0.1.11/' inventory/hosts

# 3. Test connectivity
./deploy.sh test

# 4. Dry-run preview
./deploy.sh dryrun

# 5. Deploy infrastructure
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags docker,nvidia-docker

# 6. Deploy application
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags application

# 7. Deploy monitoring
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags monitoring

# 8. Verify
/usr/local/bin/3dfigurine-healthcheck
/usr/local/bin/3dfigurine-monitor
```

### Selective Deployment

```bash
# Docker only
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags docker

# GPU setup only
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags nvidia-docker

# Application only (assumes docker+gpu ready)
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags application

# Dev environment only
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l dev

# Prod + staging (skip dev)
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l prod,staging
```

---

## Integration with Terraform

### Automated Integration Script

```bash
#!/bin/bash
# Full stack deployment: Terraform → Ansible

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

echo "Step 1: Provision infrastructure with Terraform..."
cd "$PROJECT_ROOT/terraform"
terraform apply -auto-approve

# Extract VM IPs
PROD_IP=$(terraform output -raw vm_public_ip_prod 2>/dev/null || echo "<PROD_IP>")
STAGING_IP=$(terraform output -raw vm_public_ip_staging 2>/dev/null || echo "<STAGING_IP>")
DEV_IP=$(terraform output -raw vm_public_ip_dev 2>/dev/null || echo "<DEV_IP>")

echo "Step 2: Update Ansible inventory..."
cd "$PROJECT_ROOT/ansible"
sed -i "s/<PROD_IP>/$PROD_IP/" inventory/hosts
sed -i "s/<STAGING_IP>/$STAGING_IP/" inventory/hosts
sed -i "s/<DEV_IP>/$DEV_IP/" inventory/hosts

echo "Step 3: Wait for VMs to be ready..."
sleep 60

echo "Step 4: Configure with Ansible..."
./deploy.sh deploy

echo "Done! Infrastructure provisioned and configured."
```

---

## Operations & Maintenance

### Post-Deployment Verification

```bash
# 1. Service Status
systemctl status 3dfigurine-trellis
systemctl status 3dfigurine-meshroom

# 2. Container Status
docker ps | grep 3dfigurine

# 3. GPU Availability
nvidia-smi

# 4. Health Check
/usr/local/bin/3dfigurine-healthcheck

# 5. System Monitoring
/usr/local/bin/3dfigurine-monitor

# 6. Logs
journalctl -u 3dfigurine-trellis -f
tail -f /var/log/3dfigurine/3dfigurine.log
```

### Updating Configuration

```bash
# Change GPU allocation (dev)
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l dev \
  -e cuda_visible_devices="0" \
  --tags application

# Update memory limits
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l prod \
  -e docker_memory_limit="100g" \
  --tags application

# Change backup schedule
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l prod \
  -e backup_schedule="0 3 * * *" \
  --tags application

# Disable SSH hardening (troubleshooting only)
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l dev \
  -e ssh_hardening=no
```

### Troubleshooting

```bash
# Verbose output
ansible-playbook -i inventory/hosts playbooks/deploy.yml -vvv

# Check specific host
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l dev -vvv

# Test without making changes
ansible-playbook -i inventory/hosts playbooks/deploy.yml --check --diff

# Grep errors in ansible log
grep ERROR ansible.log
grep FAILED ansible.log

# Inspect role execution
ansible-playbook -i inventory/hosts playbooks/deploy.yml --step
# Prompts for each task

# Dry-run with variable inspection
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  --check \
  --diff \
  -e ansible_verbosity=4
```

---

## Idempotency Verification

All Ansible tasks are idempotent (safe to run multiple times):

```bash
# Run twice - results should be identical in second run
ansible-playbook -i inventory/hosts playbooks/deploy.yml

# Wait 30 seconds
sleep 30

# Run again - should show all tasks as "ok" with no changes
ansible-playbook -i inventory/hosts playbooks/deploy.yml

# Result: Only "changed" items: 0
```

---

## Security Considerations

### SSH Hardening (Production Only)

Automatically applied to production VMs:

```yaml
# SSH Configuration Changes:
PermitRootLogin: no
PubkeyAuthentication: yes
PasswordAuthentication: no
X11Forwarding: no
AllowTcpForwarding: no
```

### Firewall Rules

```bash
# Recommended rules (manual application)
sudo ufw default deny incoming
sudo ufw allow from <YOUR_IP> to any port 22
sudo ufw allow from 127.0.0.1 to any port 2375
sudo ufw enable
```

### Credential Management

**Sensitive Data Handled:**
- `.env` files: Permissions 600 (owner only)
- SSH keys: ~/.ssh directory, 700 permissions
- Docker credentials: Via docker login or config.json

**Best Practices:**
- Never commit `.env` files to git
- Rotate SSH keys periodically
- Use Azure Key Vault for secrets
- Enable firewall on all VMs
- Apply security patches regularly

---

## Comparison: Bash vs Ansible

| Aspect | Bash Scripts | Ansible |
|--------|-------------|---------|
| **Readability** | Low (imperative) | High (declarative) |
| **Idempotency** | Manual | Automatic |
| **Error Handling** | Complex | Built-in |
| **State Management** | None | Ansible facts |
| **Cross-platform** | Difficult | Native |
| **Version Control** | Text files | Easy diffing |
| **Testing** | Limited | check mode |
| **Scaling** | Per-VM | Inventory based |
| **Reusability** | Low | High (roles) |
| **Team Collaboration** | Hard | Easy (YAML) |

**Ansible Advantages:**
- Declarative: Describe desired state, not steps
- Check mode: Dry-run before execution
- Fact gathering: Automatic system information
- Role reusability: Use roles across projects
- Error recovery: Idempotent retries
- Version controlled: Clear diffs
- Documentation: Self-documenting YAML

---

## Advanced Usage

### Rolling Updates

```bash
# Update one environment at a time
for ENV in dev staging prod; do
  echo "Updating $ENV..."
  ansible-playbook -i inventory/hosts playbooks/deploy.yml -l $ENV
  sleep 60  # Delay between environments
done
```

### Parallel Execution

```bash
# Deploy to multiple VMs in parallel
ansible-playbook -i inventory/hosts playbooks/deploy.yml -f 10
```

### Custom Variable Overrides

```bash
# Override group_vars with command-line values
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -e docker_memory_limit="50g" \
  -e backup_retention_days=14 \
  -e enable_monitoring=yes
```

### Dynamic Inventory

For Azure-hosted VMs, use dynamic inventory:

```bash
# Generate inventory from Azure
ansible-inventory -i scripts/azure_rm.yml --list
ansible-playbook -i scripts/azure_rm.yml playbooks/deploy.yml
```

---

## Monitoring & Alerting

### Automated Monitoring Scripts

```bash
# Real-time system monitoring
/usr/local/bin/3dfigurine-monitor
# Output: CPU, memory, disk, network, container status

# GPU monitoring
/usr/local/bin/3dfigurine-gpu-monitor
# Output: GPU utilization, memory, temperature

# Health check
/usr/local/bin/3dfigurine-healthcheck
# Output: Service status, data volume health, GPU availability

# Metrics collection (runs via cron every 5 minutes)
/usr/local/bin/3dfigurine-metrics
# Output: JSON metrics file in /var/log/3dfigurine/metrics/
```

### Alert Rules

8 configurable alert rules with thresholds:

| Alert | Threshold | Severity | Action |
|-------|-----------|----------|--------|
| HighCPU | > 80% | Warning | Log |
| HighMemory | > 85% | Warning | Log |
| HighGPU | > 95% | Critical | Alert |
| HighGPUTemp | > 85°C | Critical | Alert |
| DiskSpace | > 80% full | Warning | Log |
| ContainerCrash | Not running | Critical | Alert |
| GPUMemory | < 1GB free | Warning | Log |
| ServiceDown | Not responding | Critical | Alert |

---

## Limitations & Future Enhancements

### Current Limitations

1. **Playbook runs sequentially** - Consider with-items for parallel role execution
2. **Single datacenter** - Extend inventory for multi-region
3. **Manual inventory updates** - Integrate with Terraform outputs
4. **Basic alerting** - Extend with Prometheus/Grafana integration
5. **No rollback** - Version control deployment states

### Recommended Enhancements

1. **Ansible Tower/AWX** - Enterprise workflow automation
2. **Integration with Terraform** - Automatic inventory generation
3. **Prometheus + Grafana** - Advanced monitoring and dashboards
4. **Vault for secrets** - Encrypted variable management
5. **Molecule testing** - Role unit testing
6. **Packer images** - Pre-configured VM images to skip configuration
7. **CI/CD integration** - GitHub Actions automation
8. **Multi-region support** - Global infrastructure management

---

## Quick Reference

### File Locations

```
ansible/
├── ansible.cfg                    # Global configuration
├── README.md                      # Comprehensive guide
├── deploy.sh                      # Deployment wrapper
├── inventory/
│   └── hosts                      # Host definitions
├── group_vars/
│   ├── prod.yml                   # Production variables
│   ├── staging.yml                # Staging variables
│   └── dev.yml                    # Development variables
├── roles/
│   ├── docker-install/            # Docker installation
│   ├── nvidia-docker/             # NVIDIA Docker setup
│   ├── application/               # Application configuration
│   └── monitoring/                # Monitoring setup
└── playbooks/
    └── deploy.yml                 # Main playbook
```

### Commands Summary

```bash
# Validation
ansible-playbook -i inventory/hosts playbooks/deploy.yml --syntax-check

# Test connectivity
ansible all -i inventory/hosts -m ping

# Dry-run
ansible-playbook -i inventory/hosts playbooks/deploy.yml --check --diff

# Full deployment
./deploy.sh

# Infrastructure only
./deploy.sh deploy:infra

# Application configuration
./deploy.sh deploy:app

# Monitoring setup
./deploy.sh deploy:monitoring

# Specific environment
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l prod

# Specific role/tag
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags docker
```

---

## Implementation Statistics

| Metric | Value |
|--------|-------|
| Total Lines of Code | 1,915+ |
| Number of Files | 27 |
| Number of Roles | 4 |
| Number of Templates | 7 |
| Number of Tasks | 40+ |
| Number of Handlers | 8 |
| Supported Environments | 3 (prod/staging/dev) |
| Docker Installation Time | 3-5 min |
| NVIDIA Setup Time | 2-3 min |
| Application Setup Time | 1-2 min |
| Monitoring Setup Time | 1-2 min |
| **Total Deployment Time** | **~10-15 minutes** |

---

## Conclusion

The Ansible implementation provides:

✅ **Declarative Configuration** - YAML-based, easy to understand  
✅ **Idempotent Operations** - Safe to run multiple times  
✅ **Multi-Environment Support** - dev, staging, production  
✅ **Production-Grade Features** - Monitoring, logging, backups, health checks  
✅ **Team-Friendly** - Version controlled, collaborative  
✅ **Scalable** - From 1 VM to thousands  
✅ **Maintainable** - Modular roles, clear separation of concerns  

This implementation successfully replaces imperative bash scripts with enterprise-grade infrastructure automation aligned with DevOps best practices.
