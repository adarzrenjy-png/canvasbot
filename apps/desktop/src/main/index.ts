import { app, BrowserWindow, ipcMain, nativeTheme, shell } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { BackendProcess } from './backend.js'
import { CanvasSession } from './canvas-session.js'
import { CredentialVault } from './credential-vault.js'
import { ProviderCatalog } from './provider-catalog.js'

const currentDir = path.dirname(fileURLToPath(import.meta.url))
// dist/main/index.js -> apps/desktop -> apps -> repo root
const repoRoot = path.resolve(currentDir, '../../../..')

const canvasSession = new CanvasSession()
const credentialVault = new CredentialVault()
const providerCatalog = new ProviderCatalog(credentialVault)
const backend = new BackendProcess(repoRoot)

/** Match the renderer's first paint so launch never flashes the wrong colour. */
const windowBackground = () => (nativeTheme.shouldUseDarkColors ? '#212121' : '#ffffff')

function rendererEntry(): { devUrl?: string; file: string } {
  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl) return { devUrl, file: '' }
  // Packaged builds carry the compiled UI next to the app code inside the asar.
  const base = app.isPackaged ? path.join(app.getAppPath(), 'apps/frontend/dist') : path.join(repoRoot, 'apps/frontend/dist')
  return { file: path.join(base, 'index.html') }
}

function createWindow(apiBaseUrl: string): BrowserWindow {
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
      // The renderer needs the port before its first fetch, and argv is the
      // only channel available synchronously at preload time.
      additionalArguments: [`--cadence-api-base=${apiBaseUrl}`],
    },
  })

  window.once('ready-to-show', () => window.show())

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })

  const { devUrl, file } = rendererEntry()
  if (devUrl) void window.loadURL(devUrl)
  else void window.loadFile(file)

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
ipcMain.handle('provider:list-models', (_event, provider: string) => providerCatalog.listModels(provider))

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
    let apiBaseUrl: string
    try {
      const handle = await backend.start()
      apiBaseUrl = handle.baseUrl
    } catch (error) {
      createErrorWindow(error instanceof Error ? error.message : 'The planner service failed to start.', backend.recentLog)
      return
    }

    createWindow(apiBaseUrl)
    nativeTheme.on('updated', () => {
      for (const window of BrowserWindow.getAllWindows()) window.setBackgroundColor(windowBackground())
    })
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow(apiBaseUrl)
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  void canvasSession.close()
  backend.stop()
})
