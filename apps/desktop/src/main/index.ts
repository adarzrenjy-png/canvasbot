import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { CanvasSession } from './canvas-session.js'
import { CredentialVault } from './credential-vault.js'
import { ProviderCatalog } from './provider-catalog.js'

const currentDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(currentDir, '../../../..')
const canvasSession = new CanvasSession()
const credentialVault = new CredentialVault()
const providerCatalog = new ProviderCatalog(credentialVault)
let backend: ChildProcess | null = null

function startBackend() {
  if (backend) return
  const python = process.env.CADENCE_PYTHON || path.join(repoRoot, '.venv', 'bin', 'python')
  backend = spawn(python, ['-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  backend.on('exit', () => { backend = null })
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1360, height: 900, minWidth: 940, minHeight: 650,
    title: 'Cadence Academic OS',
    backgroundColor: '#f4f4ef',
    webPreferences: { preload: path.join(currentDir, '../preload/index.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  })
  window.webContents.setWindowOpenHandler(({ url }) => { if (url.startsWith('https://')) void shell.openExternal(url); return { action: 'deny' } })
  const devUrl = process.env.VITE_DEV_SERVER_URL
  if (devUrl) void window.loadURL(devUrl)
  else void window.loadFile(path.join(repoRoot, 'apps/frontend/dist/index.html'))
}

ipcMain.handle('canvas:connect', () => canvasSession.connect())
ipcMain.handle('canvas:status', () => canvasSession.getStatus())
ipcMain.handle('provider:save-key', async (_event, provider: string, apiKey: string) => { await providerCatalog.saveKey(provider, apiKey); return { stored: true } })
ipcMain.handle('provider:has-key', (_event, provider: string) => providerCatalog.hasKey(provider))
ipcMain.handle('provider:list-models', (_event, provider: string) => providerCatalog.listModels(provider))

app.whenReady().then(() => { startBackend(); createWindow(); app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() }) })
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('before-quit', () => { void canvasSession.close(); backend?.kill('SIGTERM') })
