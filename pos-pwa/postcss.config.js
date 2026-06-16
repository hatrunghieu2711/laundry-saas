// Tự thêm prefix (-webkit-, …) cho trình duyệt cũ trên máy POS Sunmi (Android 6,
// Chrome ~44–56). Target lấy từ "browserslist" trong package.json (dùng chung với
// @vitejs/plugin-legacy). Autoprefixer KHÔNG backport CSS Grid hiện đại cho Chrome
// cũ → các layout nhiều cột đã được chuyển sang flexbox trong index.css.
export default {
  plugins: {
    autoprefixer: {},
  },
}
