import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Proxy /api -> backend FastAPI (:8000) para evitar CORS no dev.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // @leafygreen-ui/emotion puxa @emotion/server (SSR) que quebra no browser.
      '@emotion/server/create-instance': fileURLToPath(
        new URL('./src/emotion-server-stub.js', import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
