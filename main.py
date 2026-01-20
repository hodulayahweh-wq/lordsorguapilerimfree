import os, json, re
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"]

DATA_DIR = "data"
STATE_FILE = "state.json"

os.makedirs(DATA_DIR, exist_ok=True)

if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w") as f:
        json.dump({}, f)

def load_state():
    with open(STATE_FILE) as f:
        return json.load(f)

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def clean(name):
    return re.sub(r"[^a-z0-9_]", "", name.lower())

app = FastAPI()
tg = Application.builder().token(BOT_TOKEN).build()

# ---------- BOT ----------
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("✅ Sistem aktif\nTXT gönder → API oluşur")

async def upload(u: Update, c: ContextTypes.DEFAULT_TYPE):
    d = u.message.document
    if not d.file_name.endswith(".txt"):
        return
    name = clean(d.file_name.replace(".txt", ""))
    path = f"{DATA_DIR}/{name}.txt"
    f = await d.get_file()
    await f.download_to_drive(path)

    s = load_state()
    s[name] = True
    save_state(s)

    await u.message.reply_text(f"✅ API hazır:\n/search/{name}?q=test")

tg.add_handler(CommandHandler("start", start))
tg.add_handler(MessageHandler(filters.Document.ALL, upload))

# ---------- API ----------
@app.get("/search/{dataset}")
def search(dataset: str, q: str):
    dataset = clean(dataset)
    s = load_state()
    if dataset not in s:
        raise HTTPException(404, "Yok")

    path = f"{DATA_DIR}/{dataset}.txt"
    if not os.path.exists(path):
        raise HTTPException(404, "Dosya yok")

    res = []
    with open(path, errors="ignore") as f:
        for line in f:
            if q.lower() in line.lower():
                res.append(line.strip())
            if len(res) >= 100:
                break
    return {"count": len(res), "data": res}

# ---------- WEBHOOK ----------
@app.on_event("startup")
async def on():
    await tg.initialize()
    await tg.bot.set_webhook(f"{BASE_URL}/webhook")

@app.post("/webhook")
async def hook(r: Request):
    data = await r.json()
    await tg.process_update(Update.de_json(data, tg.bot))
    return {"ok": True}

@app.get("/")
def root():
    return {"status": "online"}
