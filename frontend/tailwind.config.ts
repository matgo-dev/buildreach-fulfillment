import type { Config } from "tailwindcss";
import { colors } from "./src/lib/tokens";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: colors.brand,
          dark: colors.brandDark,
          light: colors.brandLight,
        },
      },
    },
  },
  plugins: [],
};

export default config;
