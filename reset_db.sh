#!/bin/bash

# ============================
# RESET RAILS DATABASE SCRIPT
# ============================
# This script drops, recreates, and migrates the Rails database.
# It also forcefully terminates any existing DB connections before dropping.

set -e  # Exit on any error

# ----------------------------
# CONFIGURATION
# ----------------------------
APP_DIR="/home/opc/oct/my_api_app"
RAILS_ENV="development"
DB_USER="postgres"    # change if your DB user differs
DB_NAME="my_api_app_development"  # adjust to your actual DB name

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
function info() { echo -e "\033[1;34m[INFO]\033[0m $1"; }
function success() { echo -e "\033[1;32m[SUCCESS]\033[0m $1"; }
function error() { echo -e "\033[1;31m[ERROR]\033[0m $1"; }

# ----------------------------
# NAVIGATE TO APP
# ----------------------------
cd "$APP_DIR" || { error "App directory not found: $APP_DIR"; exit 1; }

info "🔍 Checking database connections..."
psql -U "$DB_USER" -d postgres -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();
" || info "No active connections found or failed to terminate connections."

# ----------------------------
# DATABASE RESET COMMANDS
# ----------------------------
info "💣 Dropping database..."
bundle exec rails db:drop RAILS_ENV=$RAILS_ENV || info "Database already dropped."

info "🧱 Creating database..."
bundle exec rails db:create RAILS_ENV=$RAILS_ENV

info "🧩 Running migrations..."
bundle exec rails db:migrate RAILS_ENV=$RAILS_ENV

# Uncomment below line if you want to seed automatically
# info "🌱 Seeding database..."
# bundle exec rails db:seed RAILS_ENV=$RAILS_ENV

success "✅ Database reset completed successfully!"
