import { app } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { createServer } from 'node:net'
import path from 'node:path'

export type BackendHandle = {
  port: number
  baseUrl: string
  /** Shared secret required to push provider API keys into the backend. */
  runtimeToken: string
}

/** Ask the OS for a free loopback port so two copies of the app never collide. */
export function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (address === null || typeof address === 'string') {
        server.close()
        reject(new Error('Could not reserve a local port for the planner service'))
        return
      }
      const { port } = address
      server.close(() => resolve(port))
    })
  })
}

/**
 * Locate the backend process to run.
 *
 * A packaged build ships a PyInstaller binary in Contents/Resources/backend.
 * A checkout runs the module out of the project virtualenv instead, so a
 * developer's edits take effect without a rebuild.
 */
export function resolveBackendCommand(repoRoot: string): { command: string; args: string[]; cwd: string } {
  const override = process.env.CADENCE_BACKEND_BIN
  if (override) return { command: override, args: [], cwd: path.dirname(override) }

  if (app.isPackaged) {
    const binary = path.join(process.resourcesPath, 'backend', 'cadence-backend')
    return { command: binary, args: [], cwd: path.join(process.resourcesPath, 'backend') }
  }

  const venvPython = path.join(repoRoot, '.venv', 'bin', 'python')
  const python = process.env.CADENCE_PYTHON || (existsSync(venvPython) ? venvPython : 'python3')
  return { command: python, args: [path.join(repoRoot, 'packaging', 'backend_entry.py')], cwd: repoRoot }
}

/** Poll the API until it answers, so the window never opens onto a dead backend. */
export async function waitForBackend(baseUrl: string, timeoutMs = 45_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastError: unknown = null

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/status`, { signal: AbortSignal.timeout(2_000) })
      if (response.ok) return
      lastError = new Error(`planner service replied with HTTP ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }

  const detail = lastError instanceof Error ? lastError.message : String(lastError)
  throw new Error(`The planner service did not start within ${Math.round(timeoutMs / 1000)}s (${detail})`)
}

export class BackendProcess {
  private child: ChildProcess | null = null
  private handle: BackendHandle | null = null
  // Fresh per launch, so a stale token can never be replayed against a new run.
  private readonly runtimeToken = randomBytes(32).toString('hex')
  /** Recent stderr, surfaced in the error window when startup fails. */
  private log: string[] = []

  constructor(private readonly repoRoot: string) {}

  get baseUrl(): string | null {
    return this.handle?.baseUrl ?? null
  }

  get token(): string {
    return this.runtimeToken
  }

  get recentLog(): string {
    return this.log.join('')
  }

  async start(): Promise<BackendHandle> {
    if (this.handle) return this.handle

    const port = Number(process.env.CADENCE_API_PORT) || (await findFreePort())
    const baseUrl = `http://127.0.0.1:${port}`
    const { command, args, cwd } = resolveBackendCommand(this.repoRoot)

    if (command !== 'python3' && !existsSync(command)) {
      throw new Error(`The planner service executable is missing at ${command}`)
    }

    // SQLite lives in the per-user data directory. Inside a signed .app the
    // bundle itself is read-only, so the database can never sit beside the code.
    const databasePath = path.join(app.getPath('userData'), 'planner.db')

    this.child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        CADENCE_API_HOST: '127.0.0.1',
        CADENCE_API_PORT: String(port),
        DATABASE_URL: `sqlite:///${databasePath}`,
        RUNTIME_TOKEN: this.runtimeToken,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    const record = (chunk: Buffer) => {
      this.log.push(chunk.toString())
      if (this.log.length > 80) this.log.shift()
    }
    this.child.stdout?.on('data', record)
    this.child.stderr?.on('data', record)

    let exited: { code: number | null; signal: NodeJS.Signals | null } | null = null
    this.child.on('exit', (code, signal) => {
      exited = { code, signal }
      this.child = null
      this.handle = null
    })

    const spawnFailed = new Promise<never>((_resolve, reject) => {
      this.child?.once('error', error => reject(new Error(`Could not launch the planner service: ${error.message}`)))
    })

    await Promise.race([waitForBackend(baseUrl), spawnFailed])

    if (exited) {
      const { code, signal } = exited as { code: number | null; signal: NodeJS.Signals | null }
      throw new Error(`The planner service exited early (code ${code ?? 'null'}, signal ${signal ?? 'none'})`)
    }

    this.handle = { port, baseUrl, runtimeToken: this.runtimeToken }
    return this.handle
  }

  stop(): void {
    this.child?.kill('SIGTERM')
    this.child = null
    this.handle = null
  }
}
