#!/bin/bash

# Step 1: Create new React app with TypeScript
npx create-react-app my-blue-app-1 --template typescript

# Step 2: Move into app directory
cd my-blue-app-1

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

# Step 7: Create Header component
mkdir -p src/components

cat > src/components/Header.tsx << 'EOL'
import React from 'react';

const Header: React.FC = () => {
  return (
    <header className="bg-primary-dark shadow-lg">
      <nav className="container mx-auto px-6 py-4">
        <div className="flex items-center justify-between">
          {/* Logo */}
          <div className="text-2xl font-bold text-white">
            BlueApp
          </div>

          {/* Navigation Menu - Only Home */}
          <ul className="flex space-x-8">
            <li>
              <a
                href="#home"
                className="text-white hover:text-primary-light transition duration-300 font-medium"
              >
                Home
              </a>
            </li>
          </ul>
        </div>
      </nav>
    </header>
  );
};

export default Header;
EOL

# Step 8: Update App.tsx to include Header and blank page
cat > src/App.tsx << 'EOL'
import React from 'react';
import Header from './components/Header';

function App() {
  return (
    <div className="min-h-screen bg-primary">
      <Header />
      <main className="container mx-auto px-6 py-12">
        {/* Blank page - no content */}
      </main>
    </div>
  );
}

export default App;
EOL

# Step 9: Start the app
npm start