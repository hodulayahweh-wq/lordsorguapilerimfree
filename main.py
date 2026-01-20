import os
import json
import re
import zipfile
from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response
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
BASE_URL = os.environ.get("BASE_URL")          # Ör: https://lordapiv3.onrender.com

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
app = FastAPI(title="LordApiV3 - Dosya/Klasör → Search API")

# ──────────────────────────────────────────────
# Telegram Application (global, tek sefer initialize edilecek)
application = Application.builder().token(BOT_TOKEN).build()

# ───── Handler'lar ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Sistem aktif\n\n"
        "📂 TXT veya ZIP (klasör) dosya gönder → otomatik API oluşur\n"
        "📌 Komutlar: /listele  /sil  /kapat  /ac"
    )

async def file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        return

    doc = update.message.document
    file_name = doc.file_name.lower()
    original_name = clean_name(doc.file_name.replace(".txt", "").replace(".zip", ""))

    file = await doc.get_file()
    temp_path = os.path.join(DATA_DIR, doc.file_name)
    await file.download_to_drive(temp_path)

    state = load_state()
    created_apis = []

    if file_name.endswith(".zip"):
        # ZIP ise unzip et, içindeki TXT'leri işle
        unzip_dir = os.path.join(DATA_DIR, original_name)
        os.makedirs(unzip_dir, exist_ok=True)
        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_dir)
        
        for root, _, files in os.walk(unzip_dir):
            for f in files:
                if f.lower().endswith(".txt"):
                    name = clean_name(f.replace(".txt", "")) + "_result"
                    path = os.path.join(DATA_DIR, f"{name}.txt")
                    src_path = os.path.join(root, f)
                    os.rename(src_path, path)  # Taşı
                    state[name] = {"active": True, "source": "zip"}
                    created_apis.append(name)
        
        os.remove(temp_path)  # Temp zip sil
    elif file_name.endswith(".txt"):
        # Tek TXT
        name = original_name + "_result"
        path = os.path.join(DATA_DIR, f"{name}.txt")
        os.rename(temp_path, path)
        state[name] = {"active": True, "source": "txt"}
        created_apis.append(name)
    else:
        os.remove(temp_path)
        await update.message.reply_text("Sadece .txt veya .zip dosyası kabul edilir.")
        return

    save_state(state)

    if created_apis:
        msg = "✅ API(ler) oluşturuldu:\n"
        for api in created_apis:
            msg += f"{BASE_URL}/search/{api}?q=ornek_arama\n"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("ZIP içinde TXT bulunamadı.")

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
        # Çok veri varsa TXT olarak dön
        content = "\n".join(results)
        return Response(content=content, media_type="text/plain", headers={"Content-Disposition": "attachment; filename=results.txt"})
    
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
