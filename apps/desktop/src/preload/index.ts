import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('academicOS', {
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
