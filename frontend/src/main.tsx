import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import FluxLines from './FluxLines';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div className="flux-background" aria-hidden="true">
      <FluxLines
        colors={['#ffffff', '#ffffff', '#ffffff']}
        glow={2}
        rimWidth={0.2}
        lineWidth={1}
        flowDirection="down"
        mouseInteraction
        clickSwirl
        speed={0.5}
        scale={1.6}
        turbulence={1}
        fluidity={0.1}
        sharpness={2.5}
        shimmer={1.5}
        mouseStrength={1}
        mouseRadius={0.35}
        intro
        lightMode={false}
      />
    </div>
    <div className="app-content">
      <BrowserRouter><App /></BrowserRouter>
    </div>
  </React.StrictMode>,
);
