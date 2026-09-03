import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer, request, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import path from 'node:path'

/**
 * Serves the built renderer and reverse-proxies /api to the local backend.
 *
 * Loading the UI over file:// caused every API call to fail in a packaged
 * build: file:// documents have an opaque ("null") origin, which puts the
 * request through CORS and Chromium's local-network checks, and it forced the
 * backend port to be smuggled to the renderer through preload argv.
 *
 * Serving both from one http://127.0.0.1 origin removes all of that. The
 * renderer just calls a relative /api/v1 path, same-origin, no preflight, no
 * port handoff.
 */

const MIME_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
}

function proxyToBackend(clientRequest: IncomingMessage, response: ServerResponse, backendOrigin: string): void {
  const target = new URL(backendOrigin)
  const upstream = request(
    {
      hostname: target.hostname,
      port: target.port,
      path: clientRequest.url,
      method: clientRequest.method,
      headers: { ...clientRequest.headers, host: target.host },
    },
    upstreamResponse => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers)
      upstreamResponse.pipe(response)
    },
  )

  upstream.on('error', error => {
    if (response.headersSent) {
      response.destroy()
      return
    }
    response.writeHead(502, { 'content-type': 'application/json; charset=utf-8' })
    response.end(JSON.stringify({ detail: `The planner service is unreachable: ${error.message}` }))
  })

  clientRequest.pipe(upstream)
}

async function serveStatic(urlPath: string, rootDir: string, response: ServerResponse): Promise<void> {
  // Resolve inside rootDir and reject anything that escapes it. The server is
  // loopback-only, but a traversal bug would still expose the whole disk.
  const decoded = decodeURIComponent(urlPath.split('?')[0])
  const candidate = path.resolve(rootDir, `.${path.posix.normalize(decoded)}`)
  const withinRoot = candidate === rootDir || candidate.startsWith(rootDir + path.sep)

  let filePath = withinRoot ? candidate : rootDir
  try {
    const stats = await stat(filePath)
    if (stats.isDirectory()) filePath = path.join(filePath, 'index.html')
    await stat(filePath)
  } catch {
    // Unknown paths fall back to the SPA entry point.
    filePath = path.join(rootDir, 'index.html')
  }

  const contentType = MIME_TYPES[path.extname(filePath).toLowerCase()] ?? 'application/octet-stream'
  response.writeHead(200, { 'content-type': contentType, 'cache-control': 'no-store' })
  createReadStream(filePath).pipe(response)
}

export type UiServer = { origin: string; close: () => void }

/** Start the loopback UI server. Resolves once it is accepting connections. */
export function startUiServer(rootDir: string, backendOrigin: string): Promise<UiServer> {
  const resolvedRoot = path.resolve(rootDir)

  const server: Server = createServer((clientRequest, response) => {
    const url = clientRequest.url ?? '/'
    if (url === '/api' || url.startsWith('/api/')) {
      proxyToBackend(clientRequest, response, backendOrigin)
      return
    }
    void serveStatic(url, resolvedRoot, response)
  })

  return new Promise((resolve, reject) => {
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (address === null || typeof address === 'string') {
        server.close()
        reject(new Error('Could not determine the UI server port'))
        return
      }
      resolve({
        origin: `http://127.0.0.1:${address.port}`,
        close: () => server.close(),
      })
    })
  })
}
