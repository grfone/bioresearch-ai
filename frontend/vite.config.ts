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


import {
  defineConfig,
} from "vite";


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

});