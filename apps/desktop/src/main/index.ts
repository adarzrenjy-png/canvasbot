import { app, BrowserWindow, ipcMain, nativeTheme, shell } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { BackendProcess } from './backend.js'
import { BackendActionPlanner, BrowserAgent } from './browser-agent.js'
import { CanvasSession } from './canvas-session.js'
import { startUiServer, type UiServer } from './ui-server.js'
import { CredentialVault } from './credential-vault.js'
import { ProviderCatalog } from './provider-catalog.js'

const currentDir = path.dirname(fileURLToPath(import.meta.url))
// dist/main/index.js -> apps/desktop -> apps -> repo root
const repoRoot = path.resolve(currentDir, '../../../..')

const canvasSession = new CanvasSession()
const credentialVault = new CredentialVault()
const providerCatalog = new ProviderCatalog(credentialVault)
const backend = new BackendProcess(repoRoot)
let uiServer: UiServer | null = null
let browserAgent: BrowserAgent | null = null

/** Match the renderer's first paint so launch never flashes the wrong colour. */
const windowBackground = () => (nativeTheme.shouldUseDarkColors ? '#212121' : '#ffffff')

/** Directory holding the built renderer. Inside a packaged app it lives in the asar. */
function rendererRoot(): string {
  return app.isPackaged
    ? path.join(app.getAppPath(), 'apps/frontend/dist')
    : path.join(repoRoot, 'apps/frontend/dist')
}

function createWindow(startUrl: string): BrowserWindow {
  const window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 940,
    minHeight: 650,
    title: 'Cadence Academic OS',
    backgroundColor: windowBackground(),
    show: false,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 14 },
    webPreferences: {
      preload: path.join(currentDir, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  window.once('ready-to-show', () => window.show())

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })

  void window.loadURL(startUrl)

  return window
}

/** Last-resort window explaining why the planner service could not start. */
function createErrorWindow(message: string, detail: string): BrowserWindow {
  const window = new BrowserWindow({
    width: 720,
    height: 520,
    title: 'Cadence could not start',
    backgroundColor: windowBackground(),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  })

  const escape = (value: string) => value.replace(/[&<>]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[character] ?? character)
  const dark = nativeTheme.shouldUseDarkColors
  const page = `<!doctype html><meta charset="utf-8" />
<style>
  :root { color-scheme: ${dark ? 'dark' : 'light'}; }
  body { margin: 0; padding: 40px; font: 14px/1.6 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: ${dark ? '#212121' : '#ffffff'}; color: ${dark ? '#ececec' : '#0d0d0d'}; }
  h1 { font-size: 20px; margin: 0 0 12px; letter-spacing: -.02em; }
  p { margin: 0 0 18px; color: ${dark ? '#9b9b9b' : '#8f8f8f'}; }
  pre { background: ${dark ? '#2a2a2a' : '#f9f9f9'}; border: 1px solid ${dark ? '#3a3a3a' : '#e5e5e5'};
        border-radius: 12px; padding: 14px; overflow: auto; max-height: 260px; font-size: 12px; white-space: pre-wrap; }
</style>
<h1>Cadence could not start</h1>
<p>${escape(message)}</p>
<pre>${escape(detail || 'No output was captured from the planner service.')}</pre>`

  void window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(page)}`)
  return window
}

ipcMain.handle('canvas:connect', () => canvasSession.connect())
ipcMain.handle('canvas:status', () => canvasSession.getStatus())
ipcMain.handle('provider:save-key', async (_event, provider: string, apiKey: string) => {
  await providerCatalog.saveKey(provider, apiKey)
  return { stored: true }
})
ipcMain.handle('provider:has-key', (_event, provider: string) => providerCatalog.hasKey(provider))
ipcMain.handle('canvas:run-agent', async (_event, goal: string, maxSteps?: number) => {
  if (!browserAgent) throw new Error('The planner service is not ready yet.')
  if (typeof goal !== 'string' || !goal.trim()) throw new Error('Describe what the agent should do.')
  // Bounded so a runaway plan cannot drive the browser indefinitely.
  return browserAgent.run(goal.trim(), Math.min(Math.max(Number(maxSteps) || 25, 1), 50))
})
ipcMain.handle('provider:list-models', (_event, provider: string, baseUrl?: string | null) => providerCatalog.listModels(provider, baseUrl))

// A second copy would fight over the SQLite file and the Canvas browser profile.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const [window] = BrowserWindow.getAllWindows()
    if (!window) return
    if (window.isMinimized()) window.restore()
    window.focus()
  })

  app.whenReady().then(async () => {
    let startUrl: string
    try {
      const handle = await backend.start()
      // Stored vault keys only live in the backend's memory, so they have to be
      // handed over on every launch before the Brain can be used.
      providerCatalog.setBackendTarget({ baseUrl: handle.baseUrl, runtimeToken: handle.runtimeToken })
      void providerCatalog.syncStoredKeys()
      browserAgent = new BrowserAgent(canvasSession, new BackendActionPlanner(handle.baseUrl))
      // In development Vite serves the renderer and proxies /api itself.
      // Otherwise the UI is served from a loopback origin that proxies /api to
      // the backend, so the renderer is same-origin with the API.
      const devUrl = process.env.VITE_DEV_SERVER_URL
      if (devUrl) {
        startUrl = devUrl
      } else {
        uiServer = await startUiServer(rendererRoot(), handle.baseUrl)
        startUrl = uiServer.origin
      }
    } catch (error) {
      createErrorWindow(error instanceof Error ? error.message : 'The planner service failed to start.', backend.recentLog)
      return
    }

    createWindow(startUrl)
    nativeTheme.on('updated', () => {
      for (const window of BrowserWindow.getAllWindows()) window.setBackgroundColor(windowBackground())
    })
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow(startUrl)
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  void canvasSession.close()
  uiServer?.close()
  backend.stop()
})
