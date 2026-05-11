import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { hydrateFromUrl } from './auth';
import { flag } from './lib/featureFlags';
import './styles/tokens.css';

hydrateFromUrl();
document.documentElement.setAttribute('data-ui', flag('ui_v2') ? 'v2' : 'v1');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <BrowserRouter basename="/dashboard">
    <App />
  </BrowserRouter>,
);
