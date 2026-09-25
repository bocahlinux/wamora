import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // `host: true` binds the dev server to 0.0.0.0 instead of the default
  // localhost-only, so it's reachable from outside a Docker container via
  // a published port (docs/generated/PHASE-D-FRONTEND-DEVELOPMENT-DOCKER-DESIGN-AUDIT-REPORT.md).
  // No effect on bare-host `npm run dev` — localhost still works exactly
  // as before.
  server: {
    host: true,
  },
})
