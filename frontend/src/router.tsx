/**
 * router.tsx
 * ----------
 * Application route definitions.
 *
 * Maps URL paths to page components.
 *
 * Routes:
 * - `/`                → Home (create workspace)
 * - `/workspace/:id`   → Workspace (view papers, summary, generate report)
 * - `/report/:id`      → Report (view generated report)
 *
 * @module router
 */

import { Routes, Route } from 'react-router-dom';
import { Home } from './pages/Home';
import { Workspace } from './pages/Workspace';
import { Report } from './pages/Report';

const Router = () => {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/workspace/:workspaceId" element={<Workspace />} />
      <Route path="/report/:workspaceId" element={<Report />} />
      {/* Fallback for undefined routes */}
      <Route
        path="*"
        element={
          <div className="page section flex items-center justify-center min-h-screen">
            <div className="text-center text-secondary">
              <h2 className="text-2xl font-bold text-primary">404</h2>
              <p>Page not found.</p>
            </div>
          </div>
        }
      />
    </Routes>
  );
};

export default Router;