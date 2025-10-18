#!/bin/bash

# Replace these variables with your actual values
EC2_INSTANCE_IP="152.67.5.153"
KEY_FILE_PATH="/home/shivareddy/.ssh/id_rsa"
RAILS_REPO_URL="git@github.com:shivareddy547/oct.git"
BRANCH_NAME="oct_18_all_working_yaml_react_front"

# Connect to EC2 instance via SSH
ssh -i "$KEY_FILE_PATH" opc@"$EC2_INSTANCE_IP" << 'EOF'

# Kill any existing Rails or Ruby processes
sudo pkill -9 rails || true
sudo pkill -9 ruby || true
sudo pkill -9 npm || true

# Clone Rails application if not exists
if [ ! -d "ai" ]; then
  git clone "$RAILS_REPO_URL"
fi

# Move to the project directory
cd ai

# Reset and pull the latest changes from the specified branch
git checkout .
git fetch origin oct_18_all_working_yaml_react_front
git checkout oct_18_all_working_yaml_react_front
git pull origin oct_18_all_working_yaml_react_front

# Ensure correct Ruby shebang paths
sed -i '1s|^.*$|#!/usr/local/bin/ruby|' /home/opc/bin/bundle
sed -i '1s|^.*$|#!/usr/local/bin/ruby|' /home/opc/bin/rails

# Ensure foreman is installed for managing processes
if ! gem list foreman -i --silent; then
  echo "Installing foreman..."
  gem install foreman
fi

# Ensure Bundler is installed and install dependencies locally
gem install bundler
bundle config set --local path 'vendor/bundle'
bundle install


# Ensure Redis is running
sudo systemctl restart redis

# Redirect ports 80 and 443 to 3000 (for public access)
sudo iptables -t nat -I PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 3000
sudo iptables -t nat -I PREROUTING -p tcp --dport 443 -j REDIRECT --to-ports 3000
sudo iptables --flush

# Set application host environment variable
export APPLICATION_HOST="https://$EC2_INSTANCE_IP"
# bin/dev &

# Use ngrok to expose port 3000 (ensure ngrok is installed on your server)
ngrok http --url=awfully-quick-monkfish.ngrok-free.app 3000 &

rm -rf tmp/
bundle exec rails s -b 0.0.0.0 &

# Start the application using foreman (bin/dev)




#!/bin/bash

# ============================
# CONFIG
# ============================
REACT_PORT=4000
RAILS_PORT=3000
PYTHON_PORT=5000

REACT_PATH="/home/opc/oct/my-blue-app"
RAILS_PATH="/home/opc/oct/my_api_app"
PYTHON_SCRIPT="/home/opc/oct/multi_agent_ai.py"

# Detect your public IP automatically
PUBLIC_IP=$(curl -s ifconfig.me)
export APPLICATION_HOST="http://$PUBLIC_IP"

echo "🚀 Starting apps on $PUBLIC_IP"
echo "React:  $APPLICATION_HOST:$REACT_PORT"
echo "Rails:  $APPLICATION_HOST:$RAILS_PORT"
echo "Python: $APPLICATION_HOST:$PYTHON_PORT"

# ============================
# IPTABLES CONFIG
# ============================
echo "🔧 Checking iptables configuration..."

# If iptables is empty, just allow required ports
if ! sudo iptables -L INPUT -n | grep -q "$RAILS_PORT"; then
  echo "🧩 Configuring iptables to allow required ports..."
  sudo iptables -A INPUT -p tcp --dport $RAILS_PORT -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport $REACT_PORT -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport $PYTHON_PORT -j ACCEPT



#  # Optional: redirect 80/443 → Rails
  sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports $PYTHON_PORT
#  sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-ports $RAILS_PORT

  sudo iptables-save
else
  echo "✅ iptables already configured (skipping reconfiguration)"
fi



# ============================
# START SERVICES
# ============================

# Kill any old processes
echo "🧹 Cleaning up old processes..."
pkill -f "rails s" || true
pkill -f "npm start:4000" || true
pkill -f "python3" || true

# Start Rails API
echo "🚀 Starting Rails API on port $RAILS_PORT..."
cd "$RAILS_PATH" || exit
rm -rf tmp/
bundle exec rails s -p $RAILS_PORT -b 0.0.0.0 &

# Start React app
echo "🚀 Starting React app on port $REACT_PORT..."
cd "$REACT_PATH" || exit
npm install --silent
PORT=4000 npm start &

# Start Python UI script
echo "🚀 Starting Python UI on port $PYTHON_PORT..."
cd "$(dirname "$PYTHON_SCRIPT")" || exit
python3 "$PYTHON_SCRIPT" --port $PYTHON_PORT &

# ============================
# DONE
# ============================
sleep 3
echo "✅ All apps are now running!"
echo ""
echo "🌐 Access URLs:"
echo "🔹 Rails API:   $APPLICATION_HOST:$RAILS_PORT"
echo "🔹 React App:   $APPLICATION_HOST:$REACT_PORT"
echo "🔹 Python UI:   $APPLICATION_HOST:$PYTHON_PORT"





