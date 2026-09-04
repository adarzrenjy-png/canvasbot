export {}

declare global {
  interface Window {
    academicOS?: {
      canvas: {
        connect: () => Promise<{ status: 'closed' | 'opening' | 'connected' | 'auth_required' | 'error'; url?: string }>
        status: () => Promise<{ status: string; url: string | null; allowedOrigins: string[] }>
        runAgent: (goal: string, maxSteps?: number) => Promise<{
          status: 'finished' | 'failed' | 'exhausted'
          steps: { thought: string; action: Record<string, unknown>; result: string }[]
          result?: unknown
          reason?: string
        }>
      }
      providers: {
        saveKey: (provider: string, apiKey: string) => Promise<{ stored: boolean }>
        hasKey: (provider: string) => Promise<boolean>
        listModels: (provider: string, baseUrl?: string | null) => Promise<{ id: string; label: string }[]>
      }
    }
  }
}