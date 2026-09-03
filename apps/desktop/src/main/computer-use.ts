import { z } from 'zod'
import type { CanvasSession } from './canvas-session.js'

export const computerActionSchema = z.discriminatedUnion('action', [
  z.object({ action: z.literal('click'), selector: z.string() }),
  z.object({ action: z.literal('double_click'), selector: z.string() }),
  z.object({ action: z.literal('scroll'), deltaY: z.number().min(-5000).max(5000) }),
  z.object({ action: z.literal('type_text'), selector: z.string(), text: z.string().max(10000) }),
  z.object({ action: z.literal('press_key'), key: z.string().max(40) }),
  z.object({ action: z.literal('navigate'), url: z.string().url() }),
  z.object({ action: z.literal('go_back') }),
  z.object({ action: z.literal('wait'), milliseconds: z.number().min(50).max(10000) }),
  z.object({ action: z.literal('read_page') }),
  z.object({ action: z.literal('finish'), result: z.unknown() }),
  z.object({ action: z.literal('fail'), reason: z.string() }),
])

export type ComputerAction = z.infer<typeof computerActionSchema>

export interface ComputerUseProvider {
  createSession(): Promise<string>
  runTask(instruction: string, screenshotBase64: string): Promise<ComputerAction>
  continueTask(sessionId: string, observation: unknown, screenshotBase64: string): Promise<ComputerAction>
  cancelTask(sessionId: string): Promise<void>
  getUsage(sessionId: string): Promise<{ inputTokens: number; outputTokens: number; approximateCostUsd: number }>
}

export class CanvasActionExecutor {
  constructor(private readonly session: CanvasSession) {}

  async execute(rawAction: unknown): Promise<unknown> {
    const action = computerActionSchema.parse(rawAction)
    const page = this.session.getPage()
    switch (action.action) {
      case 'click': await page.locator(action.selector).click(); return { ok: true }
      case 'double_click': await page.locator(action.selector).dblclick(); return { ok: true }
      case 'scroll': await page.mouse.wheel(0, action.deltaY); return { ok: true }
      case 'type_text': {
        const target = page.locator(action.selector)
        if ((await target.getAttribute('type'))?.toLowerCase() === 'password') throw new Error('The Canvas worker cannot type passwords')
        await target.fill(action.text)
        return { ok: true }
      }
      case 'press_key': await page.keyboard.press(action.key); return { ok: true }
      case 'navigate': {
        if (!this.session.isAllowed(action.url)) throw new Error('Navigation is outside the configured academic origins')
        await page.goto(action.url)
        return { ok: true, url: page.url() }
      }
      case 'go_back': await page.goBack(); return { ok: true, url: page.url() }
      case 'wait': await page.waitForTimeout(action.milliseconds); return { ok: true }
      case 'read_page': return { url: page.url(), title: await page.title(), text: (await page.locator('body').innerText()).slice(0, 50000) }
      case 'finish': return { finished: true, result: action.result }
      case 'fail': return { failed: true, reason: action.reason }
    }
  }

  async screenshot(): Promise<string> {
    return (await this.session.getPage().screenshot({ type: 'jpeg', quality: 70 })).toString('base64')
  }
}
