import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Electron loads the production build from disk over file://, so every asset
  // reference has to be relative. An absolute base resolves against the
  // filesystem root and the window comes up blank.
  base: './',
})
