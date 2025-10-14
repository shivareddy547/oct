#!/bin/bash

# ============================
# SERVER CONFIG
# ============================
SERVER_IP="152.67.5.153"
KEY_PATH="/home/shivareddy/.ssh/id_rsa"
REPO_URL="git@github.com:shivareddy547/oct.git"
PROJECT_DIR="/home/opc/oct"
BRANCH="oct_14_json_changes"

# ============================
# PROCESS CLEANUP
# ============================
echo "🧹 Stopping old processes..."

# Kill Rails server
if pgrep -f "rails s" > /dev/null; then
  echo "Stopping existing Rails processes..."
  pkill -9 -f "rails s"
  sleep 1
fi

# Kill React dev server
if pgrep -f "npm start" > /dev/null; then
  echo "Stopping existing React processes..."
  pkill -9 -f "npm start"
  sleep 1
fi

# Kill Python server
if pgrep -f "python3" > /dev/null; then
  echo "Stopping existing Python processes..."
  pkill -9 -f "python3"
  sleep 1
fi

echo "✅ All old processes stopped."
redis-cli FLUSHALL
# ============================
# DEPLOY SCRIPT
# ============================
ssh -i "$KEY_PATH" opc@"$SERVER_IP" bash -s <<'EOF'
set -e

PROJECT_DIR="/home/opc/oct"
REACT_PATH="$PROJECT_DIR/my-blue-app"
RAILS_PATH="$PROJECT_DIR/my_api_app"
PYTHON_SCRIPT="$PROJECT_DIR/multi_agent_ai.py"

RAILS_PORT=3000
REACT_PORT=4000
PYTHON_PORT=5000

PUBLIC_IP=$(curl -s ifconfig.me)
export APPLICATION_HOST="http://$PUBLIC_IP"

echo "🌐 Server IP: $PUBLIC_IP"

# ============================
# CLEANUP OLD PROCESSES
# ============================
echo "🧹 Killing any processes using ports $RAILS_PORT, $REACT_PORT, $PYTHON_PORT..."

for PORT in $RAILS_PORT $REACT_PORT $PYTHON_PORT; do
  PIDS=$(sudo lsof -t -i tcp:$PORT || true)
  if [ -n "$PIDS" ]; then
    echo "Killing processes on port $PORT: $PIDS"
    sudo kill -9 $PIDS
  fi
done



# ============================
# UPDATE CODE
# ============================
cd "$PROJECT_DIR"
if [ ! -d ".git" ]; then
  git clone "git@github.com:shivareddy547/oct.git" .
fi
git fetch origin oct_14_json_changes
git reset --hard origin/oct_14_json_changes
echo "✅ Code updated successfully!"

# ============================
# START SERVICES
# ============================

# Rails
echo "🚀 Starting Rails API..."
cd "$RAILS_PATH"
rm -rf tmp/
bundle install --quiet
rails db:migrate
bundle exec rails s -p $RAILS_PORT -b 0.0.0.0 &
sleep 3
# React
echo "🚀 Starting React app on port $REACT_PORT..."
cd "$REACT_PATH" || exit
npm install --silent
nohup bash -c "PORT=$REACT_PORT npm start -- --host 0.0.0.0" > ~/react.log 2>&1 &
sleep 5
echo "✅ React started on port $REACT_PORT"

sleep 10
# Python
echo "🚀 Starting Python UI..."
cd "$(dirname "$PYTHON_SCRIPT")"
# Replace <project_path_here> with actual project paths your script expects
#nohup python3 "$PYTHON_SCRIPT" --port $PYTHON_PORT /home/opc/oct &
nohup python3 "$PYTHON_SCRIPT" --port $PYTHON_PORT "$REACT_PATH" "$RAILS_PATH"  &


# ============================
# IPTABLES
# ============================
if ! sudo iptables -L INPUT -n | grep -q "$RAILS_PORT"; then
  echo "🔧 Setting up iptables..."
  sudo iptables -A INPUT -p tcp --dport $RAILS_PORT -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport $REACT_PORT -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport $PYTHON_PORT -j ACCEPT
  sudo iptables-save
fi

echo ""
echo "✅ All apps restarted successfully!"
echo "Rails:  $APPLICATION_HOST:$RAILS_PORT"
echo "React:  $APPLICATION_HOST:$REACT_PORT"
echo "Python: $APPLICATION_HOST:$PYTHON_PORT"
EOF
