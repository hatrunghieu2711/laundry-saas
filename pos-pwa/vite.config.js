import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import legacy from '@vitejs/plugin-legacy'
import { VitePWA } from 'vite-plugin-pwa'

// Phiên bản app từ package.json → inline vào bundle (modern + legacy) qua define.
// FE đọc hằng __APP_VERSION__ (panel "Thông tin tiệm"). readFileSync: không phụ thuộc
// npm_package_version, chạy cả khi gọi vite trực tiếp.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url)))

// Frontend tĩnh: build ra dist/, nginx serve. API gọi qua /api/v1 (nginx proxy).
export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
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
    // Bản tương thích trình duyệt cũ (Android 6 / Chrome ~44–50 không hiểu ES2020
    // và không hỗ trợ <script type=module>). Sinh thêm bundle nomodule + polyfills.
    // Đặt SAU VitePWA để workbox precache cả file *-legacy*.js (globPatterns **/*.js).
    legacy({
      targets: ['chrome >= 44', 'android >= 6', 'defaults'],
    }),
  ],
  server: {
    // Dev: proxy /api về backend (docker expose 127.0.0.1:8010).
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true },
    },
  },
})
