export {}

declare global {
  interface Window {
    academicOS?: {
      /** Origin of the local planner API, e.g. http://127.0.0.1:52431 */
      apiBaseUrl: string | null
      canvas: {
        connect: () => Promise<{ status: 'closed' | 'opening' | 'connected' | 'auth_required' | 'error'; url?: string }>
        status: () => Promise<{ status: string; url: string | null; allowedOrigins: string[] }>
      }
      providers: {
        saveKey: (provider: 'openai' | 'anthropic', apiKey: string) => Promise<{ stored: boolean }>
        hasKey: (provider: 'openai' | 'anthropic') => Promise<boolean>
        listModels: (provider: 'openai' | 'anthropic') => Promise<{ id: string; label: string }[]>
      }
    }
  }
}
