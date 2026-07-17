/**
 * ============================================================================
 * App.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Root application component.
 *
 * This component composes the highest level of the frontend application.
 *
 * Responsibilities
 *
 * • Configure the application router.
 * • Mount global layouts.
 * • Provide future application-wide providers.
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *                     App
 *                      │
 *              BrowserRouter
 *                      │
 *                  App Router
 *                      │
 *         ┌────────────┼────────────┐
 *         │            │            │
 *       Home      Workspace      Report
 *
 * ----------------------------------------------------------------------------
 * Responsibilities
 * ----------------------------------------------------------------------------
 *
 * App is intentionally lightweight.
 *
 * It should never:
 *
 * • Fetch scientific data
 * • Execute research workflows
 * • Manage workspace state
 * • Perform API requests
 *
 * Those responsibilities belong to:
 *
 * • API clients
 * • React Query
 * • Zustand stores
 * • Backend services
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import { BrowserRouter } from "react-router-dom";

import Router from "./router";

function App() {

    return (

        <BrowserRouter>

            <Router />

        </BrowserRouter>

    );

}

export default App;