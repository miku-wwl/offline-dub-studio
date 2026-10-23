import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://localhost:7860', '/healthz': 'http://localhost:7860' } },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.ts' },
})
