import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Proxy /api -> backend FastAPI (:8180) para evitar CORS no dev.
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
    // Porta dedicada da POC TJGO — 5173 colide com outras POCs locais (Vite default).
    port: 5180,
    strictPort: true, // falha alto em vez de cair silenciosamente em outra porta
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8180',
        changeOrigin: true,
      },
    },
  },
})
