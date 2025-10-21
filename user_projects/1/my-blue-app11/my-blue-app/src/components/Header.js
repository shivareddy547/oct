import React from 'react';
import { Link } from 'react-router-dom';

const Header = () => {
  return (
    <nav className="bg-blue-600 p-4">
      <div className="container mx-auto flex justify-between items-center">
        <div className="text-white text-xl font-bold">
          My Blue App
        </div>
        <div className="space-x-4">
          <Link to="/" className="text-white hover:text-blue-200">Home</Link>
          <Link to="/contact" className="text-white hover:text-blue-200">Contact Us</Link>
        </div>
      </div>
    </nav>
  );
};

export default Header;
