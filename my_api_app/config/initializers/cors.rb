Rails.application.config.middleware.insert_before 0, Rack::Cors do
  allow do
    origins '*' # or 'http://localhost:5173' if you prefer strict
    resource '*', headers: :any, methods: [:get, :post, :put, :patch, :delete, :options, :head]
  end
end
