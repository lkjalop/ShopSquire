import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import { AppErrorBoundary } from './components/AppErrorBoundary.tsx';
import { getOrCreateStoredUid } from './lib/browserSession';

const params = new URLSearchParams(window.location.search);
const StandaloneEscalationRoom = React.lazy(() => import('./components/EscalationRoom.tsx'));
const ProcurementCertificationShowcase = React.lazy(
  () => import('./components/ProcurementCertificationShowcase.tsx'),
);
const surface = params.get('surface');
const ElectronicsShopScenario = React.lazy(() => import('./components/ElectronicsShopScenario.tsx'));
const CaseContractSelection = React.lazy(() => import('./components/CaseContractSelection.tsx'));
const PortfolioQualification = React.lazy(() => import('./components/PortfolioQualification.tsx'));
const ProductOfferDemo = React.lazy(() => import('./components/ProductOfferDemo.tsx'));
const incidentId = params.get('incident_id') || '';
const token = params.get('token');
const incidentRole = params.get('role') === 'staff' ? 'staff' : 'buyer';
const content = surface === 'qualified-shop'
  ? <React.Suspense fallback={<p>Loading fictional qualification…</p>}><PortfolioQualification/></React.Suspense>
  : surface === 'product-offers'
  ? <React.Suspense fallback={<p>Loading fictional product offers...</p>}><ProductOfferDemo/></React.Suspense>
  : surface === 'case-requirements' && params.get('case_id')
  ? <main style={{maxWidth:900,margin:'32px auto',padding:16}}><h1>Review case requirements</h1>
      <React.Suspense fallback={<p>Loading case requirements…</p>}>
        <CaseContractSelection caseId={params.get('case_id')!} uid={getOrCreateStoredUid()} />
      </React.Suspense></main>
  : surface === 'electronics-shop'
  ? <React.Suspense fallback={<div role="status">Loading shop simulation...</div>}><ElectronicsShopScenario /></React.Suspense>
  : surface === 'procurement-certification'
  ? <React.Suspense fallback={<div role="status">Loading procurement certificate...</div>}>
      <ProcurementCertificationShowcase />
    </React.Suspense>
  : surface === 'incident' && incidentId && token
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
