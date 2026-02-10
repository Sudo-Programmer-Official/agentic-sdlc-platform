/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{vue,ts,js,tsx}", "./src/**/*.vue"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef5ff",
          100: "#d7e7ff",
          200: "#b3d1ff",
          300: "#87b6ff",
          400: "#5a91ff",
          500: "#336dff",
          600: "#1f53e6",
          700: "#1a42b3",
          800: "#16368a",
          900: "#122c6b"
        }
      },
      fontFamily: {
        display: ["\"Space Grotesk\"", "ui-sans-serif", "system-ui"],
        body: ["\"IBM Plex Sans\"", "ui-sans-serif", "system-ui"]
      }
    }
  },
  plugins: []
};
