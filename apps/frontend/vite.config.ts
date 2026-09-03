import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND = process.env.CADENCE_API_ORIGIN ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Electron loads the production build from a loopback HTTP origin, so assets
  // resolve relatively rather than from the server root.
  base: './',
  server: {
    // Mirrors what the desktop app's UI server does in production, keeping the
    // renderer same-origin with the API in development too.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
    },
  },
})
