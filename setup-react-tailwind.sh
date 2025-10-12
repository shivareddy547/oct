#!/bin/bash

# Step 1: Create new React app
npx create-react-app my-blue-app --template typescript

# Step 2: Move into app directory
cd my-blue-app

# Step 3: Install Tailwind CSS v3 (not v4) + PostCSS + Autoprefixer
npm install -D tailwindcss@3.4.14 postcss autoprefixer

# Step 4: Initialize Tailwind config
npx tailwindcss init -p

# Step 5: Configure Tailwind (tailwind.config.js)
cat > tailwind.config.js << 'EOL'
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          light: '#60a5fa',
          DEFAULT: '#3b82f6',
          dark: '#1e40af',
        },
      },
    },
  },
  plugins: [],
}
EOL

# Step 6: Configure global styles (src/index.css)
cat > src/index.css << 'EOL'
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-primary text-white;
}
EOL

# Step 7: Update App.tsx to use blue theme
cat > src/App.tsx << 'EOL'
import React from 'react';

function App() {
  return (
    <div className="flex h-screen items-center justify-center bg-primary">
      <h1 className="text-4xl font-bold">Welcome to Blue Themed React + Tailwind 3 App</h1>
    </div>
  );
}

export default App;
EOL

# Step 8: Start the app
npm start