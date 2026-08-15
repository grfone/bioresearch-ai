/**
 * Vite configuration for BioResearch AI frontend.
 *
 * Purpose
 * -------
 * Configures the React development environment and build pipeline.
 *
 * Responsibilities:
 *
 * - Enable React support.
 * - Configure development server.
 * - Configure API proxy.
 * - Define production build behavior.
 *
 * Architecture
 * ------------
 *
 * React Frontend
 *
 *        |
 *        |
 *        HTTP
 *
 *        |
 *        |
 *
 * FastAPI Backend
 *
 *
 * During development:
 *
 * Browser
 *    |
 * localhost:5173
 *    |
 * Vite proxy
 *    |
 * localhost:8000
 *
 *
 * Author
 * ------
 * Guillermo Ramajo Fernández
 */


/// <reference types="vitest" />
import {
  defineConfig,
} from "vitest/config";


import react from "@vitejs/plugin-react";



export default defineConfig({

  plugins: [

    react(),

  ],



  server: {

    port: 5173,


    host: "localhost",


    proxy: {

      "/api": {

        target:
          "http://localhost:8000",

        changeOrigin:
          true,

        secure:
          false,

      },

    },

  },


  build: {

    outDir:
      "dist",


    sourcemap:
      true,

  },

  test: {

    /**
     * Default to jsdom so anything that touches document / window
     * doesn\'t fail. Tests that don\'t need a DOM can override with
     * ``// @vitest-environment node`` at the top of the file.
     */
    environment: "jsdom",

    /**
     * Match the same file extensions as production so we don\'t
     * accidentally skip tests written in either flavour.
     */
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
    ],

    /**
     * Setup file — runs before every test. Loads jest-dom
     * matchers (toBeInTheDocument, etc.) so component tests
     * read like documentation.
     */
    setupFiles: ["./src/test/setup.ts"],

    /**
     * CSS imports in component tests are noise. Reset them so
     * importing a component doesn\'t pull the whole stylesheet.
     */
    css: false,
  },

});