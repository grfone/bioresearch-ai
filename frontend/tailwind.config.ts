/**
 * Tailwind CSS configuration for BioResearch AI frontend.
 *
 * Purpose
 * -------
 * Defines the visual language of the scientific research interface.
 *
 * The design system follows:
 *
 * - Modern biotechnology interfaces.
 * - Scientific visualization dashboards.
 * - AI research operation centers.
 * - Apple Human Interface Guidelines principles.
 *
 * Design goals:
 *
 * - Minimal visual noise.
 * - Strong information hierarchy.
 * - Calm futuristic appearance.
 * - High readability.
 *
 * Author
 * ------
 * Guillermo Ramajo Fernández
 */

// @ts-ignore
import typography from '@tailwindcss/typography';
import type { Config } from "tailwindcss";


const config: Config = {

  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],


  theme: {

    extend: {

      colors: {

        background: {
          DEFAULT: "#08111F",
          secondary: "#0B1020",
          surface: "#111827",
        },


        primary: {

          DEFAULT: "#2D8CFF",
          light: "#4DA3FF",
          bright: "#64B5FF",

        },


        scientific: {

          blue: "#3B82F6",
          purple: "#6366F1",
          violet: "#8B5CF6",

        },


        biology: {

          teal: "#22D3EE",

        },


        status: {

          success: "#34D399",
          warning: "#FBBF24",

        },


        text: {

          primary: "#FFFFFF",
          secondary: "#CBD5E1",
          muted: "#94A3B8",

        },

      },


      borderRadius: {

        card: "18px",
        panel: "20px",

      },


      boxShadow: {

        scientific:
          "0 0 40px rgba(45,140,255,0.15)",

        glow:
          "0 0 25px rgba(77,163,255,0.25)",

      },


      backgroundImage: {

        "scientific-gradient":
          "linear-gradient(135deg,#3B82F6,#6366F1,#8B5CF6)",

      },


      fontFamily: {

        sans: [
          "Inter",
          "Geist",
          "IBM Plex Sans",
          "SF Pro Display",
          "sans-serif",
        ],

      },


      transitionDuration: {

        slow:
          "700ms",

      },

    },

  },

  plugins: [
    typography
  ],
};

export default config;