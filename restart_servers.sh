#!/bin/bash

# ============================
# SERVER CONFIG
# ============================
RAILS_PORT=3000
REACT_PORT=4000

# ============================
# STOP OLD PROCESSES
# ============================
echo "🧹 Stopping old Rails and React processes..."

for PROC in "rails s" "npm start"; do
  if pgrep -f "$PROC" > /dev/null; then
    echo "Stopping $PROC..."
    pkill -9 -f "$PROC"
    sleep 1
  fi
done

echo "✅ All old processes stopped."

# ============================
# START SERVICES
# ============================

# Rails
echo "🚀 Starting Rails API..."
# Adjust to your Rails project path
RAILS_PATH="/home/opc/oct/my_api_app"
cd "$RAILS_PATH" || exit
bundle install --quiet
rails db:migrate
bundle exec rails s -p $RAILS_PORT -b 0.0.0.0 &
sleep 3

# React
echo "🚀 Starting React app..."
# Adjust to your React project path
REACT_PATH="/home/opc/oct/my-blue-app"
cd "$REACT_PATH" || exit
npm install --silent
nohup bash -c "PORT=$REACT_PORT npm start -- --host 0.0.0.0" > ~/react.log 2>&1 &
sleep 5
echo "✅ React started on port $REACT_PORT"

# ============================
# UPDATE IPTABLES
# ============================
echo "🔧 Configuring iptables..."

for PORT in $RAILS_PORT $REACT_PORT; do
  if ! sudo iptables -L INPUT -n | grep -q "$PORT"; then
    sudo iptables -A INPUT -p tcp --dport $PORT -j ACCEPT
  fi
done

sudo iptables-save
echo "✅ iptables updated successfully!"
