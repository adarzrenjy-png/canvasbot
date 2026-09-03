import { z } from 'zod'
import type { CredentialVault } from './credential-vault.js'

export const providerIdSchema = z.enum(['openai', 'anthropic', 'zai', 'custom'])
export type ProviderId = z.infer<typeof providerIdSchema>

export const PROVIDER_IDS: ProviderId[] = ['openai', 'anthropic', 'zai', 'custom']

const PROVIDER_LABELS: Record<ProviderId, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  zai: 'Z.AI',
  custom: 'this endpoint',
}

/** Default hosts. "custom" has none: the user supplies a base URL. */
const DEFAULT_BASE_URLS: Partial<Record<ProviderId, string>> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  zai: 'https://api.z.ai/api/paas/v4',
}

const openAIResponseSchema = z.object({
  data: z.array(z.object({ id: z.string().min(1), owned_by: z.string().optional() })),
})

const anthropicResponseSchema = z.object({
  data: z.array(z.object({
    id: z.string().min(1),
    display_name: z.string().optional(),
    created_at: z.string().optional(),
  })),
})

export type ProviderModel = { id: string; label: string }

const credentialKey = (provider: ProviderId) => `${provider}_api_key`

function providerError(provider: ProviderId, status: number): Error {
  const name = PROVIDER_LABELS[provider]
  if (status === 401 || status === 403) return new Error(`${name} rejected this API key or it lacks model access.`)
  if (status === 404) return new Error(`${name} has no model list at this URL. Check the base URL includes the API version path.`)
  if (status === 429) return new Error(`${name} rate-limited the model request. Try again shortly.`)
  return new Error(`${name} could not list models (HTTP ${status}).`)
}

function resolveBaseUrl(provider: ProviderId, baseUrl?: string | null): string {
  const resolved = (baseUrl || DEFAULT_BASE_URLS[provider] || '').trim().replace(/\/+$/, '')
  if (!resolved) throw new Error('Enter the base URL for this endpoint, for example http://localhost:11434/v1')
  let parsed: URL
  try {
    parsed = new URL(resolved)
  } catch {
    throw new Error(`"${resolved}" is not a valid URL.`)
  }
  // A key would otherwise be sent in the clear to an arbitrary host.
  const loopback = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1' || parsed.hostname === '::1'
  if (parsed.protocol !== 'https:' && !loopback) {
    throw new Error('Use https for remote endpoints so the API key is not sent in the clear.')
  }
  return resolved
}

export async function fetchProviderModels(provider: ProviderId, apiKey: string, baseUrl?: string | null): Promise<ProviderModel[]> {
  const root = resolveBaseUrl(provider, baseUrl)
  const request: { url: string; headers: Record<string, string> } = provider === 'anthropic'
    ? { url: `${root}/models?limit=1000`, headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' } }
    : { url: `${root}/models`, headers: { Authorization: `Bearer ${apiKey}` } }

  const response = await fetch(request.url, { headers: request.headers, signal: AbortSignal.timeout(15_000) })
  if (!response.ok) throw providerError(provider, response.status)
  const payload: unknown = await response.json()

  if (provider === 'anthropic') {
    return anthropicResponseSchema.parse(payload).data.map(model => ({ id: model.id, label: model.display_name || model.id }))
  }

  const models = openAIResponseSchema.parse(payload).data

  // OpenAI's catalogue mixes in speech, image, and embedding models that cannot
  // serve as a Brain. Other OpenAI-compatible hosts list only what they serve,
  // so filtering there would hide valid models.
  const filtered = provider === 'openai'
    ? models.filter(model => /^(gpt-|o[1-9](?:-|$)|chatgpt-)/.test(model.id) && !/(audio|realtime|transcri|tts|image|search|moderation|embedding|codex)/i.test(model.id))
    : models

  return filtered
    .map(model => ({ id: model.id, label: model.id }))
    .sort((left, right) => left.id.localeCompare(right.id, undefined, { numeric: true }))
}

/** Where the backend lives, and the secret that lets us push keys into it. */
export type BackendTarget = { baseUrl: string; runtimeToken: string }

export class ProviderCatalog {
  private target: BackendTarget | null = null

  constructor(private readonly vault: CredentialVault) {}

  /** Called once the backend is up, so stored keys can be pushed to it. */
  setBackendTarget(target: BackendTarget): void {
    this.target = target
  }

  /**
   * Hand a key to the backend for this run only.
   *
   * The vault is the system of record; the backend keeps the key in memory and
   * never writes it to SQLite, so it has to be re-pushed on every launch.
   */
  private async pushToBackend(provider: ProviderId, apiKey: string): Promise<void> {
    if (!this.target) return
    try {
      const response = await fetch(`${this.target.baseUrl}/api/v1/providers/${provider}/credential`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Cadence-Runtime-Token': this.target.runtimeToken },
        body: JSON.stringify({ api_key: apiKey }),
        signal: AbortSignal.timeout(10_000),
      })
      if (!response.ok) console.error(`Could not hand the ${provider} key to the planner service: HTTP ${response.status}`)
    } catch (error) {
      console.error(`Could not hand the ${provider} key to the planner service:`, error)
    }
  }

  /** Push every stored key at startup so the Brain is live without re-entry. */
  async syncStoredKeys(): Promise<void> {
    for (const provider of PROVIDER_IDS) {
      const apiKey = await this.vault.getForMainProcess(credentialKey(provider))
      if (apiKey) await this.pushToBackend(provider, apiKey)
    }
  }

  async saveKey(rawProvider: string, apiKey: string): Promise<void> {
    const provider = providerIdSchema.parse(rawProvider)
    const normalized = apiKey.trim()
    if (normalized.length < 12) throw new Error('Enter a valid API key.')
    await this.vault.set(credentialKey(provider), normalized)
    await this.pushToBackend(provider, normalized)
  }

  async hasKey(rawProvider: string): Promise<boolean> {
    const provider = providerIdSchema.parse(rawProvider)
    return await this.vault.has(credentialKey(provider))
  }

  async listModels(rawProvider: string, baseUrl?: string | null): Promise<ProviderModel[]> {
    const provider = providerIdSchema.parse(rawProvider)
    const apiKey = await this.vault.getForMainProcess(credentialKey(provider))
    if (!apiKey) throw new Error(`No ${PROVIDER_LABELS[provider]} API key is stored.`)
    return fetchProviderModels(provider, apiKey, baseUrl)
  }
}
