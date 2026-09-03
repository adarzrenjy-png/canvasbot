import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('academicOS', {
  canvas: {
    connect: () => ipcRenderer.invoke('canvas:connect'),
    status: () => ipcRenderer.invoke('canvas:status'),
  },
  providers: {
    saveKey: (provider: string, apiKey: string) => ipcRenderer.invoke('provider:save-key', provider, apiKey),
    hasKey: (provider: string) => ipcRenderer.invoke('provider:has-key', provider),
    listModels: (provider: string, baseUrl?: string | null) => ipcRenderer.invoke('provider:list-models', provider, baseUrl),
  },
})
