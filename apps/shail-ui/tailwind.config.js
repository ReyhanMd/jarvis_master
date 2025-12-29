/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'shail-blue': '#00D4FF',
        'shail-dark': '#0A0E27',
        'shail-darker': '#050815',
      },
      backdropBlur: {
        'glass': '20px',
      },
    },
  },
  plugins: [],
}

