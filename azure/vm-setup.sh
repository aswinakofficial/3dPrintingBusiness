#!/bin/bash
# VM Setup Script for 3D Figurine Lab on Azure
# Installs Docker, NVIDIA Docker runtime, and configures the environment

set -e

echo "=== 3D Figurine Lab VM Configuration ==="
echo ""

# Update system packages
echo "Updating system packages..."
apt-get update
apt-get upgrade -y

# Install Docker
echo "Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
rm get-docker.sh

# Add current user to docker group
usermod -aG docker ${SUDO_USER:-$(whoami)} || true

# Install NVIDIA Docker runtime
echo "Installing NVIDIA Docker runtime..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
    tee /etc/apt/sources.list.d/nvidia-docker.list
apt-get update
apt-get install -y nvidia-docker2
systemctl restart docker

# Verify Docker installation
echo "Verifying Docker installation..."
docker --version
docker run --rm hello-world

# Verify NVIDIA Docker
echo "Verifying NVIDIA Docker runtime..."
docker run --rm --gpus all nvidia/cuda:12.4.1-base nvidia-smi

# Create directories for volumes
echo "Creating application directories..."
mkdir -p /opt/3dfigurine/input
mkdir -p /opt/3dfigurine/output
mkdir -p /opt/3dfigurine/logs
chmod 777 /opt/3dfigurine/input
chmod 777 /opt/3dfigurine/output
chmod 777 /opt/3dfigurine/logs

# Create systemd service for TRELLIS.2 (optional)
cat > /etc/systemd/system/3dfigurine-trellis.service << 'EOF'
[Unit]
Description=3D Figurine Lab - TRELLIS.2 Engine
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
User=docker
ExecStart=/usr/bin/docker run --rm \
  --name 3dfigurine-trellis \
  --gpus all \
  -v /opt/3dfigurine/input:/app/input \
  -v /opt/3dfigurine/output:/app/output \
  -v /opt/3dfigurine/logs:/app/logs \
  3dfigurine-trellis:latest

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Create systemd service for Meshroom (optional)
cat > /etc/systemd/system/3dfigurine-meshroom.service << 'EOF'
[Unit]
Description=3D Figurine Lab - Meshroom Engine
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
User=docker
ExecStart=/usr/bin/docker run --rm \
  --name 3dfigurine-meshroom \
  --gpus all \
  -v /opt/3dfigurine/input:/app/input \
  -v /opt/3dfigurine/output:/app/output \
  -v /opt/3dfigurine/logs:/app/logs \
  3dfigurine-meshroom:latest

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "=== VM Configuration Complete ==="
echo ""
echo "Next steps:"
echo "1. Pull Docker images from ACR: docker pull <registry>/3dfigurine-trellis:latest"
echo "2. Start services: systemctl start 3dfigurine-trellis"
echo "3. View logs: journalctl -u 3dfigurine-trellis -f"
echo "4. Check GPU: nvidia-smi"
echo ""
