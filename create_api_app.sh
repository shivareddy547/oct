#!/usr/bin/env bash
set -e

# === Configuration ===
APP_NAME=${1:-my_api_app}
DB_USERNAME=${2:-postgres}
DB_PASSWORD=${3:-root}
DB_HOST=${4:-localhost}

# === Create Rails API App ===
echo "🚀 Creating new Rails API application: $APP_NAME"
rails new $APP_NAME --api -d postgresql

cd $APP_NAME

# === Update database.yml ===
echo "🛠️ Configuring database.yml"
cat > config/database.yml <<YAML
default: &default
  adapter: postgresql
  encoding: unicode
  pool: <%= ENV.fetch("RAILS_MAX_THREADS") { 5 } %>
  username: $DB_USERNAME
  password: $DB_PASSWORD
  host: $DB_HOST

development:
  <<: *default
  database: ${APP_NAME}_development

test:
  <<: *default
  database: ${APP_NAME}_test

production:
  <<: *default
  database: ${APP_NAME}_production
  username: <%= ENV['${APP_NAME^^}_DATABASE_USERNAME'] %>
  password: <%= ENV['${APP_NAME^^}_DATABASE_PASSWORD'] %>
YAML

# === Setup database ===
echo "🧱 Setting up PostgreSQL database..."
bin/rails db:create db:migrate

# === Git Init ===
echo "📦 Initializing Git repository..."
git init
git add .
git commit -m "Initial commit - API-only Rails app"

# === Run Server ===
echo "🎉 Setup complete! Starting Rails server on http://localhost:3000"
bin/rails server
