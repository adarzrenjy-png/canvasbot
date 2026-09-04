import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND = process.env.CADENCE_API_ORIGIN ?? 'http://127.0.0.1:8000'

const root = JSON.parse(readFileSync(fileURLToPath(new URL('../../package.json', import.meta.url)), 'utf8'))

/** Short commit the bundle was built from, so two builds are never confusable. */
function gitCommit(): string {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA.slice(0, 7)
  try {
    return execSync('git rev-parse --short HEAD', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    // A source tarball with no .git is still buildable; the marker just says so.
    return 'nogit'
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Electron loads the production build from a loopback HTTP origin, so assets
  // resolve relatively rather than from the server root.
  base: './',
  define: {
    __BUILD_NUMBER__: JSON.stringify(root.buildNumber ?? 0),
    __APP_VERSION__: JSON.stringify(root.version ?? '0.0.0'),
    __GIT_COMMIT__: JSON.stringify(gitCommit()),
  },
  server: {
    // Mirrors what the desktop app's UI server does in production, keeping the
    // renderer same-origin with the API in development too.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
    },
  },
})
