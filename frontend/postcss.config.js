/**
 * ============================================================================
 * postcss.config.js
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Configures PostCSS for the BioResearch AI frontend.
 *
 * PostCSS is the CSS processor that transforms modern CSS and Tailwind
 * directives into standard CSS understood by browsers.
 *
 * ----------------------------------------------------------------------------
 * Responsibilities
 * ----------------------------------------------------------------------------
 *
 * - Enable Tailwind CSS processing.
 * - Apply Autoprefixer for cross-browser compatibility.
 * - Integrate with Vite's build pipeline.
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *              Vite Build
 *                  │
 *                  ▼
 *          postcss.config.js
 *                  │
 *      ┌───────────┴───────────┐
 *      │                       │
 * tailwindcss           autoprefixer
 *      │                       │
 *      └───────────┬───────────┘
 *                  │
 *                  ▼
 *         Standard CSS output
 *
 * ----------------------------------------------------------------------------
 * Dependencies
 * ----------------------------------------------------------------------------
 *
 * - tailwindcss: ^3.4.7
 * - autoprefixer: ^10.4.19
 *
 * Both are installed as devDependencies in package.json.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

// postcss.config.js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};