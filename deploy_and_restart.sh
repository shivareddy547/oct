#!/bin/bash

# ============================
# SERVER CONFIG
# ============================
SERVER_IP="152.67.5.153"
KEY_PATH="/home/shivareddy/.ssh/id_rsa"
REPO_URL="git@github.com:shivareddy547/oct.git"
PROJECT_DIR="/home/opc/oct"
BRANCH="main"

# ============================
# DEPLOY SCRIPT
# ============================
ssh -i "$KEY_PATH" opc@"$SERVER_IP" bash -s <<EOF
  set -e

  echo "🔁 Updating code on server..."
  cd $PROJECT_DIR

  if [ ! -d ".git" ]; then
    echo "🧩 Cloning repository fresh..."
    git clone $REPO_URL .
  fi

  echo "📦 Pulling latest code..."
  git fetch origin $BRANCH
  git reset --hard origin/$BRANCH

  echo "✅ Code updated successfully!"

  # ============================
  # RESTART ALL SERVICES
  # ============================

  REACT_PORT=4000
  RAILS_PORT=3000
  PYTHON_PORT=5000

  REACT_PATH="$PROJECT_DIR/my-blue-app"
  RAILS_PATH="$PROJECT_DIR/my_api_app"
  PYTHON_SCRIPT="$PROJECT_DIR/multi_agent_ai.py"

  PUBLIC_IP=\$(curl -s ifconfig.me)
  export APPLICATION_HOST="http://\$PUBLIC_IP"

  echo "🌐 Server IP: \$PUBLIC_IP"
  echo "React:  \$APPLICATION_HOST:\$REACT_PORT"
  echo "Rails:  \$APPLICATION_HOST:\$RAILS_PORT"
  echo "Python: \$APPLICATION_HOST:\$PYTHON_PORT"

  # ============================
  # PROCESS CLEANUP
  # ============================
  echo "🧹 Stopping old processes..."
  pkill -f "rails s" || true
  pkill -f "npm start" || true
  pkill -f "python3" || true

  # ============================
  # START RAILS
  # ============================
  echo "🚀 Starting Rails API..."
  cd "\$RAILS_PATH"
  rm -rf tmp/
  bundle install --quiet
  bundle exec rails s -p \$RAILS_PORT -b 0.0.0.0 &

  # ============================
  # START REACT
  # ============================
  echo "🚀 Starting React app..."
  cd "\$REACT_PATH"
  npm install --silent
  npm start -- --port \$REACT_PORT &

  # ============================
  # START PYTHON
  # ============================
  echo "🚀 Starting Python UI..."
  cd "\$(dirname "\$PYTHON_SCRIPT")"
  python3 "\$PYTHON_SCRIPT" --port \$PYTHON_PORT &

  # ============================
  # IPTABLES (only if needed)
  # ============================
  if ! sudo iptables -L INPUT -n | grep -q "\$RAILS_PORT"; then
    echo "🔧 Setting up iptables..."
    sudo iptables -A INPUT -p tcp --dport \$RAILS_PORT -j ACCEPT
    sudo iptables -A INPUT -p tcp --dport \$REACT_PORT -j ACCEPT
    sudo iptables -A INPUT -p tcp --dport \$PYTHON_PORT -j ACCEPT
    sudo iptables-save
  fi

  echo ""
  echo "✅ All apps restarted successfully!"
  echo "Rails:  \$APPLICATION_HOST:\$RAILS_PORT"
  echo "React:  \$APPLICATION_HOST:\$REACT_PORT"
  echo "Python: \$APPLICATION_HOST:\$PYTHON_PORT"
EOF
