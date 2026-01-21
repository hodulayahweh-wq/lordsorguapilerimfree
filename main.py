import os
import json
import re
import zipfile
import asyncio
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
# Ortam değişkenleri (Render → Environment Variables)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = os.environ.get("BASE_URL")

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
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_]", "", name)
    return name

# ──────────────────────────────────────────────
app = FastAPI(title="LordApiV3 - Dosya → Arama API")

application = Application.builder().token(BOT_TOKEN).build()

# ───── Progress mesajı güncelleme ─────
async def update_progress_message(message, percent: int, text_prefix="İşleniyor"):
    bar_length = 12
    filled = int(bar_length * percent / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    new_text = f"{text_prefix} % {percent}\n`{bar}`"
    try:
        await message.edit_text(new_text, parse_mode="Markdown")
    except:
        pass

# ───── Dosya yükleme + progress ─────
async def file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        return

    doc = update.message.document
    file_name = doc.file_name.lower()
    base_name = clean_name(doc.file_name.rsplit(".", 1)[0])

    progress_msg = await update.message.reply_text("📥 Dosya indiriliyor... % 0\n`░░░░░░░░░░░░`")

    file = await doc.get_file()
    temp_path = os.path.join(DATA_DIR, f"temp_{doc.file_id}")

    await update_progress_message(progress_msg, 10, "Dosya indiriliyor")
    await file.download_to_drive(temp_path)
    await update_progress_message(progress_msg, 30, "Dosya indirildi, işleniyor")

    state = load_state()
    created_apis = []

    if file_name.endswith(".zip"):
        unzip_dir = os.path.join(DATA_DIR, f"unzip_{base_name}_{doc.file_id[:8]}")
        os.makedirs(unzip_dir, exist_ok=True)

        await update_progress_message(progress_msg, 40, "ZIP açılıyor")

        try:
            with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                total_files = len(zip_ref.namelist())
                processed = 0

                for member in zip_ref.namelist():
                    if member.lower().endswith(".txt"):
                        zip_ref.extract(member, unzip_dir)
                        processed += 1
                        percent = 40 + int(50 * processed / max(1, total_files))
                        await update_progress_message(progress_msg, min(percent, 95))

                        fname = os.path.basename(member)
                        api_name = clean_name(fname.rsplit(".", 1)[0]) + "_result"
                        target_path = os.path.join(DATA_DIR, f"{api_name}.txt")
                        os.replace(os.path.join(unzip_dir, member), target_path)

                        state[api_name] = {"active": True, "source": "zip"}
                        created_apis.append(api_name)

                # Temizlik
                for root, dirs, files in os.walk(unzip_dir, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
                os.rmdir(unzip_dir)

        except Exception as e:
            await progress_msg.edit_text(f"Hata: ZIP açılamadı → {str(e)}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return

    elif file_name.endswith(".txt"):
        await update_progress_message(progress_msg, 60, "TXT işleniyor")
        api_name = base_name + "_result"
        target_path = os.path.join(DATA_DIR, f"{api_name}.txt")
        os.replace(temp_path, target_path)
        state[api_name] = {"active": True, "source": "txt"}
        created_apis.append(api_name)

    else:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        await progress_msg.edit_text("Sadece .txt veya .zip kabul edilir.")
        return

    if os.path.exists(temp_path):
        os.remove(temp_path)

    if created_apis:
        save_state(state)
        await update_progress_message(progress_msg, 100, "Tamamlandı")
        await asyncio.sleep(1.2)

        msg = "✅ API'ler hazır!\n\n"
        for api in created_apis:
            msg += f"• {BASE_URL}/search/{api}?q=kelime\n"
        await progress_msg.edit_text(msg)
    else:
        await progress_msg.edit_text("İşlenecek .txt dosyası bulunamadı.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Sistem çalışıyor\n"
        "📄 .txt veya .zip (içinde txt dosyaları olan) atın\n"
        "Büyük dosyalarda % ilerleme gösterilir\n\n"
        "Komutlar:\n/listele\n/sil <apiadı>\n/kapat <apiadı>\n/ac <apiadı>"
    )


async def listele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    if not state:
        await update.message.reply_text("❌ Henüz oluşturulmuş API yok.")
        return

    msg = "Mevcut API'ler:\n\n"
    for k, v in state.items():
        durum = "🟢 Açık" if v.get("active", False) else "🔴 Kapalı"
        msg += f"• {k} → {durum}\n"

    await update.message.reply_text(msg.strip() or "Liste boş.")


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
        await update.message.reply_text(f"❌ '{api}' isminde API bulunamadı.")


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
        await update.message.reply_text(f"❌ '{api}' isminde API bulunamadı.")


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
        except FileNotFoundError:
            pass
        await update.message.reply_text(f"🗑️ {api} silindi.")
    else:
        await update.message.reply_text(f"❌ '{api}' isminde API bulunamadı.")


# ───── Handler'lar ─────
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("listele", listele))
application.add_handler(CommandHandler("kapat", kapat))
application.add_handler(CommandHandler("ac", ac))
application.add_handler(CommandHandler("sil", sil))
application.add_handler(MessageHandler(filters.Document.ALL, file_upload))


# ───── Arama Endpoint ─────
@app.get("/search/{dataset}")
async def search(dataset: str, q: str = ""):
    dataset = clean_name(dataset)
    state = load_state()

    if dataset not in state or not state[dataset].get("active", False):
        raise HTTPException(status_code=404, detail="API kapalı veya mevcut değil")

    path = os.path.join(DATA_DIR, f"{dataset}.txt")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Veri dosyası bulunamadı")

    results = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and q.lower() in line.lower():
                results.append(line)
            if len(results) >= 1000:
                break

    if len(results) > 100:
        content = "\n".join(results)
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={dataset}_results.txt"}
        )

    return {"count": len(results), "data": results}


# ───── Webhook & Yaşam döngüsü ─────
@app.on_event("startup")
async def on_startup():
    await application.initialize()
    webhook_url = f"{BASE_URL.rstrip('/')}/webhook"
    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
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
        update = Update.de_json(data, application.bot)
        if update:
            await application.process_update(update)
    except Exception:
        pass
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "online"}
