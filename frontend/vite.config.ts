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
      // the FastAPI backend; SSE needs buffering off, which the proxy respects.
      // 127.0.0.1 rather than localhost: macOS resolves localhost to ::1 first,
      // and uvicorn only listens on IPv4.
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
