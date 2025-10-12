import React from 'react';
import ContactForm from '../components/ContactForm';

const ContactPage = () => {
  return (
    <div className="contact-page">
      <h1>Get In Touch</h1>
      <p>We'd love to hear from you. Please fill out the form below and we'll get back to you as soon as possible.</p>
      <ContactForm />
    </div>
  );
};

export default ContactPage;
