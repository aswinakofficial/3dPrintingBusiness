# Ansible Configuration for 3D Figurine Lab

Complete Ansible-based Infrastructure Configuration as Code for deploying 3D Figurine Lab on Azure VMs.

## Overview

This Ansible configuration automates the complete VM setup after Terraform/ARM deployment:

- **Docker Installation:** Latest Docker Engine and Docker Compose
- **GPU Support:** NVIDIA Docker runtime with CUDA 12.4.1
- **Application Setup:** Systemd services, volume mounts, environment configuration
- **Monitoring:** Logging, metrics collection, health checks, alerts
- **Multi-Environment:** Separate configurations for dev, staging, production

## Prerequisites

### Local Machine (Control Node)
```bash
# Install Ansible 2.10+
pip install ansible>=2.10

# Install Azure collection (optional, for Azure dynamic inventory)
ansible-galaxy collection install azure.azcollection
```

### Managed Nodes (Azure VMs)
- Ubuntu 20.04 LTS
- SSH key-based authentication
- User: `azureuser`
- Sudo access

## Quick Start

### 1. Update Inventory

Edit `inventory/hosts` and add your VM IPs:

```ini
[prod]
3dfigurine-prod ansible_host=<PROD_IP> environment=prod

[staging]
3dfigurine-staging ansible_host=<STAGING_IP> environment=staging

[dev]
3dfigurine-dev ansible_host=<DEV_IP> environment=dev
```

### 2. Configure SSH

```bash
# Verify SSH key
ls -la ~/.ssh/azure_3dfigurine

# Test SSH connection
ssh -i ~/.ssh/azure_3dfigurine azureuser@<VM_IP>
```

### 3. Run Playbook

```bash
# Test connection (dry-run)
ansible all -i inventory/hosts -m ping

# Preview changes
ansible-playbook -i inventory/hosts playbooks/deploy.yml --check

# Deploy configuration
ansible-playbook -i inventory/hosts playbooks/deploy.yml

# Deploy specific environment
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l prod

# Deploy specific roles
ansible-playbook -i inventory/hosts playbooks/deploy.yml --tags docker,gpu
```

## Directory Structure

```
ansible/
├── ansible.cfg              ← Ansible configuration
├── inventory/
│   └── hosts               ← Host inventory (update with IPs)
├── group_vars/
│   ├── prod.yml            ← Production variables
│   ├── staging.yml         ← Staging variables
│   └── dev.yml             ← Development variables
├── roles/
│   ├── docker-install/     ← Docker installation (40 lines)
│   │   ├── tasks/main.yml
│   │   └── handlers/main.yml
│   ├── nvidia-docker/      ← NVIDIA Docker runtime (60 lines)
│   │   ├── tasks/main.yml
│   │   ├── handlers/main.yml
│   │   └── templates/daemon.json.j2
│   ├── application/        ← Application setup (80 lines)
│   │   ├── tasks/main.yml
│   │   ├── handlers/main.yml
│   │   └── templates/       ← Systemd services, config files
│   │       ├── .env.j2
│   │       ├── 3dfigurine-trellis.service.j2
│   │       ├── 3dfigurine-meshroom.service.j2
│   │       ├── backup.sh.j2
│   │       ├── healthcheck.sh.j2
│   │       └── 3dfigurine.logrotate.j2
│   └── monitoring/         ← Monitoring setup (70 lines)
│       ├── tasks/main.yml
│       ├── handlers/main.yml
│       └── templates/      ← Monitoring scripts
│           ├── system-monitor.sh.j2
│           ├── gpu-monitor.sh.j2
│           ├── metrics.sh.j2
│           ├── alert-rules.yml.j2
│           └── log-aggregation.conf.j2
└── playbooks/
    └── deploy.yml          ← Main playbook
```

## Roles Explained

### 1. docker-install

**Purpose:** Install Docker Engine and Docker Compose

**Tasks:**
- Add Docker GPG key and repository
- Install docker-ce, containerd.io, docker-compose-plugin
- Install standalone docker-compose binary
- Add azureuser to docker group
- Enable and start Docker service
- Test with hello-world container

**Advanced (Optional):**
```bash
# Install specific Docker version
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -e docker_version=24.0.0
```

### 2. nvidia-docker

**Purpose:** Install NVIDIA Docker runtime for GPU access

**Tasks:**
- Add NVIDIA GPG key and repository
- Install nvidia-docker2 and nvidia-container-toolkit
- Configure Docker daemon (daemon.json)
- Test CUDA 12.4.1 container
- Verify GPU count and availability

**Output:**
```
GPU Information (nvidia-smi output)
GPU Memory availability
CUDA Version
```

### 3. application

**Purpose:** Configure 3D Figurine Lab application

**Tasks:**
- Create data volume directories (input, output, logs, models)
- Deploy docker-compose configuration
- Generate .env file with environment variables
- Create systemd services (trellis, meshroom)
- Setup backup script
- Configure log rotation

**Services Created:**
- `3dfigurine-trellis.service` - TRELLIS.2 engine
- `3dfigurine-meshroom.service` - Meshroom engine

**Commands After Deployment:**
```bash
# Start services
sudo systemctl start 3dfigurine-trellis
sudo systemctl start 3dfigurine-meshroom

# Check status
sudo systemctl status 3dfigurine-trellis

# View logs
journalctl -u 3dfigurine-trellis -f

# Stop services
sudo systemctl stop 3dfigurine-trellis
```

### 4. monitoring

**Purpose:** Setup monitoring, logging, and alerting

**Scripts Installed:**
- `/usr/local/bin/3dfigurine-monitor` - System health status
- `/usr/local/bin/3dfigurine-gpu-monitor` - GPU real-time monitoring
- `/usr/local/bin/3dfigurine-healthcheck` - Health verification
- `/usr/local/bin/3dfigurine-metrics` - Performance metrics

**Usage:**
```bash
# Check system status
/usr/local/bin/3dfigurine-monitor

# Monitor GPU in real-time
/usr/local/bin/3dfigurine-gpu-monitor

# Full health check
/usr/local/bin/3dfigurine-healthcheck

# View metrics
cat /var/log/3dfigurine/metrics.log
```

## Environment Configuration

### Production Variables (`prod.yml`)
```yaml
environment: prod
enable_trellis: yes
enable_meshroom: yes
enable_monitoring: yes
docker_memory_limit: "80g"
docker_cpus_limit: "30"
backup_retention_days: 30
ssh_hardening: yes
```

### Staging Variables (`staging.yml`)
```yaml
environment: staging
docker_memory_limit: "60g"
docker_cpus_limit: "24"
backup_retention_days: 7
auto_update: no
```

### Development Variables (`dev.yml`)
```yaml
environment: dev
docker_memory_limit: "40g"
docker_cpus_limit: "16"
enable_backups: no
ssh_hardening: no
auto_update: yes
```

## Common Operations

### Verify Deployment

```bash
# Test SSH connectivity
ansible all -i inventory/hosts -m ping

# Check system facts
ansible all -i inventory/hosts -m setup

# Verify Docker is running
ansible all -i inventory/hosts -m shell -a "docker ps"

# Check GPU access
ansible all -i inventory/hosts -m shell -a \
  "docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi"
```

### Run Specific Tasks

```bash
# Only install Docker
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  --tags docker \
  --skip-tags nvidia-docker,application,monitoring

# Only setup monitoring
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  --tags monitoring

# Only configure applications (after Docker is ready)
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  --tags application
```

### Update Configuration

```bash
# Change GPU visibility
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -e cuda_visible_devices="0" \
  --tags application

# Disable auto-restart
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -e docker_restart_policy="no" \
  --tags application

# Update container images
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -e container_trellis_image="myregistry.azurecr.io/3dfigurine-trellis:v2.0" \
  --tags application
```

### Troubleshooting

```bash
# Run with verbose output
ansible-playbook -i inventory/hosts playbooks/deploy.yml -vvv

# Debug a specific host
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l 3dfigurine-prod \
  -vvv

# Check variable values
ansible-inventory -i inventory/hosts --host 3dfigurine-prod

# Test syntax
ansible-playbook -i inventory/hosts playbooks/deploy.yml --syntax-check
```

## Security Considerations

### SSH Hardening (Production)

Enabled automatically for production environment:
- TCP forwarding: Disabled
- X11 forwarding: Disabled
- Password authentication: Disabled
- Root login: Disabled

### Firewall Configuration

Recommended rules:
```bash
# Allow SSH from specific IPs
sudo ufw allow from <YOUR_IP> to any port 22

# Allow Docker from localhost
sudo ufw allow from 127.0.0.1 to any port 2375

# Block everything else
sudo ufw default deny incoming
```

### Credential Management

**Sensitive data handled by:**
- `.env` file (docker-compose variables) - permissions 600
- SSH keys (in ~/.ssh) - permissions 600
- Docker credentials (via docker login or .docker/config.json)

**Never commit:**
- `.env` files
- Private SSH keys
- docker-compose.yml with secrets
- ansible-vault encrypted files (use separate vaults)

## Idempotency

All Ansible tasks are idempotent:
- Safe to run multiple times
- Only updates if needed
- No duplicate installations
- Handlers restart services only if configuration changes

```bash
# Run twice - should be identical
ansible-playbook -i inventory/hosts playbooks/deploy.yml
ansible-playbook -i inventory/hosts playbooks/deploy.yml
# Both runs should show "ok" status, very few changes in 2nd run
```

## Performance Tips

### Parallel Execution

```bash
# Deploy to multiple VMs in parallel
ansible-playbook -i inventory/hosts playbooks/deploy.yml -f 5
```

### Conditional Execution

```bash
# Skip monitoring on dev (saves time)
ansible-playbook -i inventory/hosts playbooks/deploy.yml \
  -l dev \
  --skip-tags monitoring
```

### Background Playbooks

```bash
# Run as background job
nohup ansible-playbook -i inventory/hosts playbooks/deploy.yml > deploy.log 2>&1 &

# Check progress
tail -f deploy.log
```

## Integration with Terraform

Typical workflow:

```bash
# 1. Provision VMs with Terraform
cd ../terraform
terraform apply -var-file="terraform.tfvars"

# Get VM IP from Terraform output
VM_IP=$(terraform output -raw vm_public_ip)

# 2. Update Ansible inventory
sed -i "s/<PROD_IP>/$VM_IP/" ../ansible/inventory/hosts

# 3. Wait for VM to be ready
sleep 60

# 4. Configure with Ansible
cd ../ansible
ansible-playbook -i inventory/hosts playbooks/deploy.yml -l prod
```

**Automated Wrapper Script:**
```bash
#!/bin/bash
# deploy.sh - Full stack deployment

# Provision infrastructure
terraform apply -auto-approve

# Get IP
VM_IP=$(terraform output -raw vm_public_ip)

# Update inventory
sed -i "s/<PROD_IP>/$VM_IP/" ../ansible/inventory/hosts

# Wait for SSH
until ssh -i ~/.ssh/azure_3dfigurine azureuser@$VM_IP true; do
  echo "Waiting for VM to be ready..."
  sleep 10
done

# Configure with Ansible
ansible-playbook -i ../ansible/inventory/hosts ../ansible/playbooks/deploy.yml
```

## Next Steps

1. **Update inventory** with your VM IPs after Terraform deployment
2. **Run playbook:** `ansible-playbook -i inventory/hosts playbooks/deploy.yml`
3. **Verify deployment:** Check systemd services and logs
4. **Start application:** `sudo systemctl start 3dfigurine-trellis`
5. **Monitor:** Use `/usr/local/bin/3dfigurine-monitor` script

## Support

For issues:

1. Check Ansible logs: `ansible.log`
2. Verify SSH access: `ssh -i ~/.ssh/azure_3dfigurine azureuser@<IP>`
3. Review role tasks for error details
4. Run with verbose output: `-vvv` flag

---

**Ansible Version:** 2.10+
**Target OS:** Ubuntu 20.04 LTS
**Last Updated:** 2024
