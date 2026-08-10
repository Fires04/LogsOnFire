import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    // In dev, run `npm run dev` alongside `uvicorn ... --reload` and proxy
    // API/WS calls to the backend so the SPA and API share an origin, just
    // like they do in the single production container.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8123', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8123', ws: true },
    },
  },
  build: {
    outDir: 'dist',
  },
})
