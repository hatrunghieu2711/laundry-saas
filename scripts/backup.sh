#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# backup.sh — sao lưu DB SẢN XUẤT `laundry` (KHÔNG phải laundry_test).
#
#   pg_dump laundry  →  gzip  →  /root/backups/db/laundry-YYYYMMDD-HHMM.sql.gz
#   giữ 14 bản gần nhất (xóa cũ hơn)  →  gửi file về Telegram owner.
#
# Telegram: dùng bot env (BACKUP_TELEGRAM_BOT_TOKEN + BACKUP_TELEGRAM_CHAT_ID
# trong .env), nếu không có thì lấy từ tenant_settings của Giặt Ủi 2H
# (slug 'giat-ui-2h'). Không cấu hình → bỏ qua gửi (vẫn lưu file).
#
# Cron: 02:00 hằng ngày (/etc/cron.d/laundry-backup).
# Log:  /var/log/laundry-backup.log (logrotate /etc/logrotate.d/laundry-backup).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/opt/laundry-saas"
BACKUP_DIR="/root/backups/db"
LOG_FILE="/var/log/laundry-backup.log"
DB_NAME="laundry"          # ⚠️ CHỈ DB sản xuất — KHÔNG bao giờ *_test
KEEP=14                    # số bản backup giữ lại
TG_MAX_BYTES=$((49 * 1024 * 1024))   # Telegram sendDocument ~50MB; chừa biên

COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"

log() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE" >&2; }

# Mọi stderr (kể cả lỗi pg_dump) cũng vào log.
exec 2> >(tee -a "$LOG_FILE" >&2)

# ── Lưới an toàn: tuyệt đối không dump nhầm DB test ───────────────────────────
case "$DB_NAME" in
  *_test) log "TỪ CHỐI: DB_NAME='$DB_NAME' là DB test — không backup."; exit 1 ;;
esac

# Nạp .env (DB credentials + cấu hình Telegram tùy chọn).
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a; . "$PROJECT_DIR/.env"; set +a
fi
: "${POSTGRES_USER:=laundry}"
: "${POSTGRES_PASSWORD:=}"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

# Tránh chạy chồng (cron + tay) — khóa file.
exec 9>"/run/laundry-backup.lock" 2>/dev/null || exec 9>"/tmp/laundry-backup.lock"
if ! flock -n 9; then
  log "Đang có tiến trình backup khác chạy — bỏ qua lần này."
  exit 0
fi

mkdir -p "$BACKUP_DIR"
TS="$(date '+%Y%m%d-%H%M')"
OUT="$BACKUP_DIR/${DB_NAME}-${TS}.sql.gz"

log "▶ Bắt đầu backup DB '$DB_NAME' → $OUT"

# ── pg_dump trong container postgres → gzip ra host ──────────────────────────
# Local socket trong image dùng trust; vẫn truyền PGPASSWORD cho chắc.
if ! dc exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
       pg_dump -U "$POSTGRES_USER" -d "$DB_NAME" --no-owner --no-privileges \
     | gzip -9 > "$OUT"; then
  log "✖ pg_dump THẤT BẠI — xóa file dở dang."
  rm -f "$OUT"
  exit 1
fi

# Kiểm tra file hợp lệ (không rỗng + gzip toàn vẹn).
if [ ! -s "$OUT" ] || ! gzip -t "$OUT" 2>/dev/null; then
  log "✖ File backup rỗng/hỏng — xóa: $OUT"
  rm -f "$OUT"
  exit 1
fi
SIZE_H="$(du -h "$OUT" | cut -f1)"
log "✔ Đã tạo backup: $OUT ($SIZE_H)"

# ── Dọn bản cũ, giữ $KEEP bản gần nhất ───────────────────────────────────────
mapfile -t OLD < <(ls -1t "$BACKUP_DIR/${DB_NAME}-"*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  log "🧹 Xóa ${#OLD[@]} backup cũ (giữ $KEEP gần nhất)."
fi

# ── Gửi file về Telegram owner ───────────────────────────────────────────────
send_telegram() {
  local token="${BACKUP_TELEGRAM_BOT_TOKEN:-}" chat="${BACKUP_TELEGRAM_CHAT_ID:-}"

  # Fallback: lấy bot/chat từ tenant_settings của Giặt Ủi 2H.
  if [ -z "$token" ] || [ -z "$chat" ]; then
    local row
    row="$(dc exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
      psql -U "$POSTGRES_USER" -d "$DB_NAME" -tA -F$'\t' -c \
      "SELECT ts.telegram_bot_token, ts.telegram_owner_chat_id
         FROM tenant_settings ts JOIN tenants t ON t.id = ts.tenant_id
        WHERE t.slug='giat-ui-2h'
          AND ts.telegram_bot_token IS NOT NULL
          AND ts.telegram_owner_chat_id IS NOT NULL
        LIMIT 1;" 2>/dev/null | head -1)" || true
    if [ -n "$row" ]; then
      token="${row%%$'\t'*}"
      chat="${row##*$'\t'}"
    fi
  fi

  if [ -z "$token" ] || [ -z "$chat" ]; then
    log "ℹ Telegram chưa cấu hình (env BACKUP_TELEGRAM_* hoặc tenant_settings) — bỏ qua gửi."
    return 0
  fi

  local bytes caption
  bytes="$(stat -c%s "$OUT")"
  caption="🗄️ Backup DB <b>${DB_NAME}</b> — ${TS} (${SIZE_H})"

  if [ "$bytes" -gt "$TG_MAX_BYTES" ]; then
    # Quá lớn cho sendDocument → chỉ gửi tin báo.
    curl -sS --max-time 60 \
      -d chat_id="$chat" -d parse_mode=HTML \
      --data-urlencode text="⚠️ ${caption}
File ${SIZE_H} vượt giới hạn Telegram — đã lưu trên server: ${OUT}" \
      "https://api.telegram.org/bot${token}/sendMessage" >/dev/null \
      && log "✔ Telegram: đã gửi tin báo (file quá lớn để đính kèm)." \
      || log "✖ Telegram: gửi tin báo thất bại."
    return 0
  fi

  local resp
  if resp="$(curl -sS --max-time 180 \
        -F chat_id="$chat" -F parse_mode=HTML \
        -F caption="$caption" \
        -F document=@"$OUT" \
        "https://api.telegram.org/bot${token}/sendDocument")"; then
    if printf '%s' "$resp" | grep -q '"ok":true'; then
      log "✔ Telegram: đã gửi file backup về owner."
    else
      log "✖ Telegram: API trả lỗi: $(printf '%s' "$resp" | head -c 300)"
    fi
  else
    log "✖ Telegram: curl gửi file thất bại."
  fi
}

# Gửi Telegram là best-effort — KHÔNG để lỗi gửi làm fail backup (file đã an toàn).
send_telegram || log "✖ Bước Telegram lỗi (bỏ qua, file backup vẫn an toàn)."

log "■ Hoàn tất backup."
