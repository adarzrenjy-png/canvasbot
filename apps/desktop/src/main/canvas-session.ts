import { app } from 'electron'
import path from 'node:path'
import { chromium, type BrowserContext, type Page } from 'playwright'

export type CanvasSessionStatus = 'closed' | 'opening' | 'connected' | 'auth_required' | 'error'

export class CanvasSession {
  private context: BrowserContext | null = null
  private page: Page | null = null
  private status: CanvasSessionStatus = 'closed'

  private allowedOrigins(): Set<string> {
    const configured = process.env.CANVAS_ALLOWED_ORIGINS ?? 'https://rutgers.instructure.com,https://netid.rutgers.edu'
    return new Set(configured.split(',').map(value => new URL(value.trim()).origin))
  }

  isAllowed(url: string): boolean {
    try { return this.allowedOrigins().has(new URL(url).origin) } catch { return false }
  }

  async connect(): Promise<{ status: CanvasSessionStatus; url?: string }> {
    if (this.context && this.page) {
      await this.page.bringToFront()
      return { status: this.status, url: this.page.url() }
    }
    this.status = 'opening'
    const userDataDir = path.join(app.getPath('userData'), 'canvas-browser-profile')
    try {
      this.context = await chromium.launchPersistentContext(userDataDir, {
        headless: false,
        channel: process.env.CANVAS_BROWSER_CHANNEL || 'chrome',
        viewport: { width: 1280, height: 820 },
      })
      this.page = this.context.pages()[0] ?? await this.context.newPage()
      this.page.on('framenavigated', async frame => {
        if (frame !== this.page?.mainFrame() || this.isAllowed(frame.url()) || frame.url() === 'about:blank') return
        await this.page?.goBack().catch(() => undefined)
      })
      this.page.on('load', () => {
        if (!this.page) return
        const origin = new URL(this.page.url()).origin
        this.status = origin.includes('netid.rutgers.edu') ? 'auth_required' : 'connected'
      })
      this.context.on('close', () => { this.context = null; this.page = null; this.status = 'closed' })
      const startUrl = process.env.CANVAS_BASE_URL || 'https://rutgers.instructure.com'
      if (!this.isAllowed(startUrl)) throw new Error('Canvas URL is outside the configured academic origins')
      await this.page.goto(startUrl)
      this.status = new URL(this.page.url()).origin.includes('netid.rutgers.edu') ? 'auth_required' : 'connected'
      return { status: this.status, url: this.page.url() }
    } catch (error) {
      this.status = 'error'
      throw new Error(error instanceof Error ? error.message : 'Unable to open managed Canvas browser')
    }
  }

  getPage(): Page {
    if (!this.page) throw new Error('Canvas browser session is not open')
    return this.page
  }

  getStatus() {
    return { status: this.status, url: this.page?.url() ?? null, allowedOrigins: [...this.allowedOrigins()] }
  }

  async close() { await this.context?.close(); this.context = null; this.page = null; this.status = 'closed' }
}
