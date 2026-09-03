import type { Page } from 'playwright'
import { CanvasActionExecutor, computerActionSchema, type ComputerAction } from './computer-use.js'
import type { CanvasSession } from './canvas-session.js'

/**
 * A model-agnostic browser agent.
 *
 * Rather than a vendor-specific computer-use protocol built on screenshots and
 * pixel coordinates, each step sends a text description of the page to the
 * configured Brain and gets back one action from a fixed vocabulary. Any model
 * that can follow a JSON schema can drive it.
 *
 * Every interactive element is tagged with a `data-cadence-ref` attribute before
 * the page is described, so the model picks targets from a list it was shown
 * instead of inventing CSS selectors that may not match anything.
 */

export type ObservedElement = {
  ref: string
  tag: string
  type?: string
  name: string
  value?: string
}

export type Observation = {
  url: string
  title: string
  text: string
  elements: ObservedElement[]
}

export type AgentStep = {
  thought: string
  action: ComputerAction
  result: string
}

export type AgentRun = {
  status: 'finished' | 'failed' | 'exhausted'
  steps: AgentStep[]
  result?: unknown
  reason?: string
}

const MAX_ELEMENTS = 200
const MAX_TEXT = 20000

/**
 * Tag interactive elements and describe the page.
 *
 * Runs in the page context. Password inputs are reported so the model can see a
 * sign-in wall and stop, but their values are never read.
 */
export async function buildObservation(page: Page): Promise<Observation> {
  const collected = await page.evaluate(
    ({ maxElements, maxText }) => {
      const SELECTOR = [
        'a[href]', 'button', 'input', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="tab"]', '[role="checkbox"]', '[onclick]',
      ].join(',')

      const isVisible = (element: Element): boolean => {
        const rect = element.getBoundingClientRect()
        if (rect.width === 0 && rect.height === 0) return false
        const style = window.getComputedStyle(element)
        return style.visibility !== 'hidden' && style.display !== 'none'
      }

      const label = (element: Element): string => {
        const aria = element.getAttribute('aria-label')
        if (aria) return aria
        const input = element as HTMLInputElement
        if (input.labels && input.labels.length > 0) return input.labels[0].innerText || ''
        const title = element.getAttribute('title') || element.getAttribute('placeholder')
        if (title) return title
        return (element as HTMLElement).innerText || element.getAttribute('name') || ''
      }

      // Clear refs from a previous observation so numbering stays meaningful.
      for (const stale of document.querySelectorAll('[data-cadence-ref]')) {
        stale.removeAttribute('data-cadence-ref')
      }

      const elements: { ref: string; tag: string; type?: string; name: string; value?: string }[] = []
      let index = 0
      for (const element of Array.from(document.querySelectorAll(SELECTOR))) {
        if (elements.length >= maxElements) break
        if (!isVisible(element)) continue
        const ref = `e${++index}`
        element.setAttribute('data-cadence-ref', ref)
        const input = element as HTMLInputElement
        const type = input.type ? String(input.type).toLowerCase() : undefined
        elements.push({
          ref,
          tag: element.tagName.toLowerCase(),
          type,
          name: label(element).replace(/\s+/g, ' ').trim().slice(0, 300),
          // Never read back what is typed into a password field.
          value: type === 'password' ? undefined : (input.value || undefined)?.slice(0, 300),
        })
      }

      return {
        url: location.href,
        title: document.title,
        text: (document.body?.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, maxText),
        elements,
      }
    },
    { maxElements: MAX_ELEMENTS, maxText: MAX_TEXT },
  )

  return collected
}

/** Asks the local planner for the next action; the model never talks to the page. */
export type ActionPlanner = {
  next(goal: string, observation: Observation, history: { action: unknown; result: string }[]): Promise<{ thought: string; action: ComputerAction }>
}

/** Planner backed by the local backend, which holds the provider credentials. */
export class BackendActionPlanner implements ActionPlanner {
  constructor(private readonly apiBaseUrl: string) {}

  async next(goal: string, observation: Observation, history: { action: unknown; result: string }[]) {
    const response = await fetch(`${this.apiBaseUrl}/api/v1/agent/next-action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, observation, history }),
      signal: AbortSignal.timeout(90_000),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({} as { detail?: string }))
      throw new Error(detail.detail || `The planner returned HTTP ${response.status}`)
    }
    const payload = await response.json()
    // Validated here as well as server-side: the executor must never act on an
    // action shape it has not checked itself.
    return { thought: String(payload.thought ?? ''), action: computerActionSchema.parse(payload.action) }
  }
}

export class BrowserAgent {
  private readonly executor: CanvasActionExecutor

  constructor(
    private readonly session: CanvasSession,
    private readonly planner: ActionPlanner,
  ) {
    this.executor = new CanvasActionExecutor(session)
  }

  /**
   * Drive the browser toward `goal`, one observed action at a time.
   *
   * Execution failures are fed back as history rather than aborting the run, so
   * the model can choose a different element instead of the operator seeing a
   * stack trace.
   */
  async run(goal: string, maxSteps = 25): Promise<AgentRun> {
    const steps: AgentStep[] = []
    const history: { action: unknown; result: string }[] = []

    for (let step = 0; step < maxSteps; step++) {
      const page = this.session.getPage()
      const observation = await buildObservation(page)

      const { thought, action } = await this.planner.next(goal, observation, history)

      if (action.action === 'finish') {
        steps.push({ thought, action, result: 'finished' })
        return { status: 'finished', steps, result: action.result }
      }
      if (action.action === 'fail') {
        steps.push({ thought, action, result: 'failed' })
        return { status: 'failed', steps, reason: action.reason }
      }

      let result: string
      try {
        result = JSON.stringify(await this.executor.execute(action)).slice(0, 2000)
      } catch (error) {
        result = `error: ${error instanceof Error ? error.message : String(error)}`
      }

      steps.push({ thought, action, result })
      history.push({ action, result })
    }

    return { status: 'exhausted', steps, reason: `Stopped after ${maxSteps} steps without finishing.` }
  }
}
