import { z } from 'zod'
import type { CredentialVault } from './credential-vault.js'

export const providerIdSchema = z.enum(['openai', 'anthropic'])
export type ProviderId = z.infer<typeof providerIdSchema>

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
  const name = provider === 'openai' ? 'OpenAI' : 'Anthropic'
  if (status === 401 || status === 403) return new Error(`${name} rejected this API key or it lacks model access.`)
  if (status === 429) return new Error(`${name} rate-limited the model request. Try again shortly.`)
  return new Error(`${name} could not list models (HTTP ${status}).`)
}

export async function fetchProviderModels(provider: ProviderId, apiKey: string): Promise<ProviderModel[]> {
  const request: { url: string; headers: Record<string, string> } = provider === 'openai'
    ? { url: 'https://api.openai.com/v1/models', headers: { Authorization: `Bearer ${apiKey}` } }
    : { url: 'https://api.anthropic.com/v1/models?limit=1000', headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' } }
  const response = await fetch(request.url, { headers: request.headers, signal: AbortSignal.timeout(15_000) })
  if (!response.ok) throw providerError(provider, response.status)
  const payload: unknown = await response.json()

  if (provider === 'anthropic') {
    return anthropicResponseSchema.parse(payload).data.map(model => ({ id: model.id, label: model.display_name || model.id }))
  }

  const textModel = /^(gpt-|o[1-9](?:-|$)|chatgpt-)/
  const specialized = /(audio|realtime|transcri|tts|image|search|moderation|embedding|codex)/i
  return openAIResponseSchema.parse(payload).data
    .filter(model => textModel.test(model.id) && !specialized.test(model.id))
    .map(model => ({ id: model.id, label: model.id }))
    .sort((left, right) => left.id.localeCompare(right.id, undefined, { numeric: true }))
}

export class ProviderCatalog {
  constructor(private readonly vault: CredentialVault) {}

  async saveKey(rawProvider: string, apiKey: string): Promise<void> {
    const provider = providerIdSchema.parse(rawProvider)
    const normalized = apiKey.trim()
    if (normalized.length < 12) throw new Error('Enter a valid API key.')
    await this.vault.set(credentialKey(provider), normalized)
  }

  async hasKey(rawProvider: string): Promise<boolean> {
    const provider = providerIdSchema.parse(rawProvider)
    return await this.vault.has(credentialKey(provider))
  }

  async listModels(rawProvider: string): Promise<ProviderModel[]> {
    const provider = providerIdSchema.parse(rawProvider)
    const apiKey = await this.vault.getForMainProcess(credentialKey(provider))
    if (!apiKey) throw new Error(`No ${provider === 'openai' ? 'OpenAI' : 'Anthropic'} API key is stored.`)
    return fetchProviderModels(provider, apiKey)
  }
}
