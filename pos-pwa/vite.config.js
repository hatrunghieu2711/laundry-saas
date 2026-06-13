import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Frontend tĩnh: build ra dist/, nginx serve. API gọi qua /api/v1 (nginx proxy).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // iOS Safari hỗ trợ SW hạn chế: KHÔNG hứa offline-first, chỉ precache asset tĩnh.
      includeAssets: ['apple-touch-icon.png'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // KHÔNG cache /api/* — dữ liệu tài chính phải luôn lấy mới từ backend.
        navigateFallbackDenylist: [/^\/api\//],
      },
      manifest: {
        name: 'Giặt Ủi 2H POS',
        short_name: '2H POS',
        description: 'POS quản lý ca, đơn, thu tiền — Giặt Ủi 2H',
        lang: 'vi',
        theme_color: '#F97316',
        background_color: '#FFFFFF',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/maskable-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: {
    // Dev: proxy /api về backend (docker expose 127.0.0.1:8010).
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true },
    },
  },
})
