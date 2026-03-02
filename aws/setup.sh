#!/bin/bash

# Prevent interactive prompts for a smooth background execution
export DEBIAN_FRONTEND=noninteractive

# 1. Add Python PPA
sudo add-apt-repository ppa:deadsnakes/ppa -y

# 2. Consolidated update and install
# Removed GCC/G++ specifics; kept everything else in one fast batch
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev \
    xz-utils tk-dev libpcap-dev libncurses-dev autoconf automake \
    libtool pkg-config libffi-dev liblzma-dev python3-openssl git zip \
    python3.8 python3.8-venv python3.8-dev \
    net-tools dstat sysstat cmake iftop

# 3. Docker Installation (Reverted to your original method)
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
sudo usermod -aG docker ubuntu
sudo systemctl start docker

# 4. System Tuning (TCP buffers)
sudo bash -c 'cat <<EOF >> /etc/sysctl.conf
net.core.rmem_max=10485760
net.core.wmem_max=10485760
EOF'
sudo sysctl -p

# 5. Environment Aliases
echo "alias python=python3.8" >> /home/ubuntu/.bashrc

# 6. Detock Setup
cd /home/ubuntu/Detock
git checkout before-bsc-merges

# Create venv and install requirements
python3.8 -m venv /home/ubuntu/build_detock
source /home/ubuntu/build_detock/bin/activate
pip install --upgrade pip
pip install --no-cache-dir -r tools/requirements.txt

# 7. Final Prep
mkdir -p /home/ubuntu/data
sudo apt-get clean

# 8. Final Signal
touch /home/ubuntu/setup_done