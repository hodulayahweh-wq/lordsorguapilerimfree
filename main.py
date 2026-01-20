import os
import json
import re
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ──────────────────────────────────────────────
# Ortam değişkenleri (Render → Environment Variables kısmına ekle)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = os.environ.get("BASE_URL")          # Ör: https://lordapiv3-abc123.onrender.com

if not BOT_TOKEN or not BASE_URL:
    raise RuntimeError("BOT_TOKEN ve BASE_URL ortam değişkenleri tanımlı değil!")

DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "state.json")

os.makedirs(DATA_DIR, exist_ok=True)

if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w") as f:
        json.dump({}, f)

def load_state() -> dict:
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def clean_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name

# ──────────────────────────────────────────────
# FastAPI
app = FastAPI(title="LordApiV3 - TXT → Search API")

# ──────────────────────────────────────────────
# Telegram Application (global, tek sefer initialize edilecek)
application = Application.builder().token(BOT_TOKEN).build()

# ───── Handler'lar ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Sistem aktif\n\n"
        "📂 TXT dosya gönder → otomatik API oluşur\n"
        "📌 Komutlar: /listele  /sil  /kapat  /ac"
    )

async def file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Sadece .txt dosyası kabul edilir.")
        return

    name = clean_name(doc.file_name.replace(".txt", ""))
    path = os.path.join(DATA_DIR, f"{name}.txt")

    file = await doc.get_file()
    await file.download_to_drive(path)

    state = load_state()
    state[name] = {"active": True}
    save_state(state)

    await update.message.reply_text(f"✅ API oluşturuldu:\n{BASE_URL}/search/{name}")

async def listele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    if not state:
        await update.message.reply_text("❌ Henüz API yok.")
        return

    msg = "Mevcut API'ler:\n\n"
    for k, v in state.items():
        durum = "🟢 açık" if v.get("active", False) else "🔴 kapalı"
        msg += f"• {k} → {durum}\n"

    await update.message.reply_text(msg or "Liste boş.")

async def kapat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /kapat <api_adi>")
        return
    api = clean_name(context.args[0])
    state = load_state()
    if api in state:
        state[api]["active"] = False
        save_state(state)
        await update.message.reply_text(f"🔴 {api} kapatıldı.")
    else:
        await update.message.reply_text("Böyle bir API yok.")

async def ac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /ac <api_adi>")
        return
    api = clean_name(context.args[0])
    state = load_state()
    if api in state:
        state[api]["active"] = True
        save_state(state)
        await update.message.reply_text(f"🟢 {api} açıldı.")
    else:
        await update.message.reply_text("Böyle bir API yok.")

async def sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /sil <api_adi>")
        return
    api = clean_name(context.args[0])
    state = load_state()
    if api in state:
        state.pop(api, None)
        save_state(state)
        try:
            os.remove(os.path.join(DATA_DIR, f"{api}.txt"))
        except:
            pass
        await update.message.reply_text(f"🗑️ {api} silindi.")
    else:
        await update.message.reply_text("Böyle bir API yok.")

# Handler'ları ekle
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("listele", listele))
application.add_handler(CommandHandler("kapat", kapat))
application.add_handler(CommandHandler("ac", ac))
application.add_handler(CommandHandler("sil", sil))
application.add_handler(MessageHandler(filters.Document.ALL, file_upload))

# ──────────────────────────────────────────────
# Search Endpoint
@app.get("/search/{dataset}")
async def search(dataset: str, q: str = ""):
    dataset = clean_name(dataset)
    state = load_state()

    if dataset not in state or not state[dataset].get("active", False):
        raise HTTPException(404, "Bu API kapalı veya mevcut değil")

    path = os.path.join(DATA_DIR, f"{dataset}.txt")
    if not os.path.exists(path):
        raise HTTPException(404, "Veri dosyası bulunamadı")

    results = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if q.lower() in line.lower():
                results.append(line.strip())
            if len(results) >= 1000:
                break

    if len(results) > 100:
        return {"result": "too_large", "count": len(results)}

    return {"count": len(results), "data": results}

# ──────────────────────────────────────────────
# Webhook & Startup
@app.on_event("startup")
async def on_startup():
    await application.initialize()
    webhook_url = f"{BASE_URL.rstrip('/')}/webhook"
    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True   # başlangıçta eski güncellemeleri atla
    )
    print(f"Webhook ayarlandı: {webhook_url}")

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except:
        raise HTTPException(400, "Geçersiz JSON")

    update = Update.de_json(data, application.bot)
    if update:
        await application.process_update(update)

    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "online", "bot": (await application.bot.get_me()).username}
