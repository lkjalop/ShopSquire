import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import { AppErrorBoundary } from './components/AppErrorBoundary.tsx';

const params = new URLSearchParams(window.location.search);
const StandaloneEscalationRoom = React.lazy(() => import('./components/EscalationRoom.tsx'));
const surface = params.get('surface');
const incidentId = params.get('incident_id') || '';
const token = params.get('token');
const incidentRole = params.get('role') === 'staff' ? 'staff' : 'buyer';
const content = surface === 'incident' && incidentId && token
    ? <React.Suspense fallback={<div role="status">Connecting to human support...</div>}>
        <StandaloneEscalationRoom
          embedded
          incidentId={incidentId}
          buyerToken={incidentRole === 'buyer' ? token : null}
          staffToken={incidentRole === 'staff' ? token : null}
          onClose={() => undefined}
        />
      </React.Suspense>
    : <App />;

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      {content}
    </AppErrorBoundary>
  </React.StrictMode>
);
