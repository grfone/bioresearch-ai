/**
 * ============================================================================
 * main.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Application entry point.
 *
 * This module bootstraps the React application and configures the global
 * runtime required by every page.
 *
 * Responsibilities
 *
 * • Create the React root.
 * • Configure React Query.
 * • Register application-wide providers.
 * • Load the global design system.
 * • Enable React Strict Mode during development.
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *                 Browser
 *                     │
 *                     ▼
 *                 main.tsx
 *                     │
 *        ┌────────────┴────────────┐
 *        │                         │
 * React Strict Mode        QueryClientProvider
 *                     │
 *                     ▼
 *                    App
 *
 * ----------------------------------------------------------------------------
 * Business Logic
 * ----------------------------------------------------------------------------
 *
 * This module intentionally contains no business logic.
 *
 * Scientific workflows remain implemented by the FastAPI backend.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React from "react";

import ReactDOM from "react-dom/client";

import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";

import App from "./App";

/*
|--------------------------------------------------------------------------
| Global Design System
|--------------------------------------------------------------------------
|
| Loads the complete BioResearch AI visual language.
|
*/

import "./styles/index.css";

/**
 * Global React Query configuration.
 *
 * React Query is responsible for:
 *
 * • Server state caching
 * • Background synchronization
 * • Loading state management
 * • Automatic retries
 */

const queryClient = new QueryClient({

    defaultOptions: {

        queries: {

            retry: 1,

            refetchOnWindowFocus: false,

            staleTime: 60_000,

        },

    },

});

ReactDOM.createRoot(

    document.getElementById("root")!

).render(

    <React.StrictMode>

        <QueryClientProvider client={queryClient}>

            <App />

        </QueryClientProvider>

    </React.StrictMode>

);