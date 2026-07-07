import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#003366",
          dark: "#002244",
        },
      },
    },
  },
  plugins: [],
};

export default config;
