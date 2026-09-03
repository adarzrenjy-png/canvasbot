import { app, safeStorage } from 'electron'
import { promises as fs } from 'node:fs'
import path from 'node:path'

type VaultFile = Record<string, string>

export class CredentialVault {
  private get filePath() { return path.join(app.getPath('userData'), 'credentials.enc.json') }

  private async read(): Promise<VaultFile> {
    try { return JSON.parse(await fs.readFile(this.filePath, 'utf8')) as VaultFile } catch { return {} }
  }

  async set(key: string, value: string): Promise<void> {
    if (!safeStorage.isEncryptionAvailable()) throw new Error('OS credential encryption is unavailable')
    const vault = await this.read()
    vault[key] = safeStorage.encryptString(value).toString('base64')
    await fs.mkdir(path.dirname(this.filePath), { recursive: true, mode: 0o700 })
    await fs.writeFile(this.filePath, JSON.stringify(vault), { mode: 0o600 })
  }

  async has(key: string): Promise<boolean> { return Boolean((await this.read())[key]) }

  async getForMainProcess(key: string): Promise<string | null> {
    const encrypted = (await this.read())[key]
    return encrypted ? safeStorage.decryptString(Buffer.from(encrypted, 'base64')) : null
  }
}
