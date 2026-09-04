// Ambient on purpose: no import or export here, so these stay global.
// Values are substituted by Vite's `define`; see apps/frontend/vite.config.ts.

/** Increments once per merged pull request. */
declare const __BUILD_NUMBER__: number
/** Version from the workspace root package.json. */
declare const __APP_VERSION__: string
/** Short commit the bundle was built from. */
declare const __GIT_COMMIT__: string
