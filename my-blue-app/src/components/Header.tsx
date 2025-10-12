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
