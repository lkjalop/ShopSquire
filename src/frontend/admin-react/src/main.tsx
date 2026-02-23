import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import { AppErrorBoundary } from './components/AppErrorBoundary';

createRoot(document.getElementById('root')!).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>
);
