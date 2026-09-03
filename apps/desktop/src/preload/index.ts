import { contextBridge, ipcRenderer } from 'electron'

// The main process reserves a free loopback port at launch and passes it here
// via additionalArguments, so the renderer knows where the API lives before its
// first request.
const apiFlag = process.argv.find(argument => argument.startsWith('--cadence-api-base='))
const apiBaseUrl = apiFlag ? apiFlag.slice('--cadence-api-base='.length) : null

contextBridge.exposeInMainWorld('academicOS', {
  apiBaseUrl,
  canvas: {
    connect: () => ipcRenderer.invoke('canvas:connect'),
    status: () => ipcRenderer.invoke('canvas:status'),
  },
  providers: {
    saveKey: (provider: 'openai' | 'anthropic', apiKey: string) => ipcRenderer.invoke('provider:save-key', provider, apiKey),
    hasKey: (provider: 'openai' | 'anthropic') => ipcRenderer.invoke('provider:has-key', provider),
    listModels: (provider: 'openai' | 'anthropic') => ipcRenderer.invoke('provider:list-models', provider),
  },
})
