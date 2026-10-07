import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(fileURLToPath(new URL('.', import.meta.url)), './src') },
  },
  server: {
    port: 5173,
    proxy: {
      // the FastAPI backend; SSE needs buffering off, which the proxy respects
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
