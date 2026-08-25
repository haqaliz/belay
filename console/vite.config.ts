import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // In dev, the SPA runs on vite's port and talks to the console server
    // (`npm run server`, default http://127.0.0.1:8787) through this proxy.
    proxy: {
      '/api': 'http://127.0.0.1:8787',
    },
  },
  test: {
    // Server tests (*.test.ts) run in the node environment; component tests
    // (*.spec.ts) declare `@vitest-environment jsdom` in the file.
    environment: 'node',
    include: ['src/**/*.{test,spec}.ts'],
  },
})