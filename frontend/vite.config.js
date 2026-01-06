import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/media': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  // Build configuration for production
  build: {
    // Ensure API calls use relative URLs in production
    // This allows nginx to proxy /api requests to backend
    outDir: 'dist',
    assetsDir: 'assets',
  }
})

