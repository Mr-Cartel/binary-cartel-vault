import telebot
import subprocess
import os
import time
import html
from datetime import datetime
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

TOKEN = '9175870752:AAEMoJlKbvID_ENKj9YvZ5JRM2Y2qV46V2g'
VAULT_PATH = '/home/tejas/Project Nexus PDF version'
CHAT_ID_FILE = os.path.join(VAULT_PATH, 'watchdog_chat_id.txt')

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=10)
deploy_lock = threading.Lock()


def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, 'r') as f:
            val = f.read().strip()
            if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
                return int(val)
    return None


CHAT_ID = load_chat_id()


def save_chat_id(cid):
    global CHAT_ID
    CHAT_ID = cid
    with open(CHAT_ID_FILE, 'w') as f:
        f.write(str(cid))


def notify(text):
    print(f"[BOT] {text}", flush=True)
    if CHAT_ID:
        try:
            bot.send_message(CHAT_ID, text, parse_mode="HTML")
        except Exception as e:
            print(f"[TELEGRAM WARNING] Could not send message: {e}", flush=True)


def run_cmd(cmd):
    result = subprocess.run(
        cmd,
        cwd=VAULT_PATH,
        capture_output=True,
        text=True
    )
    print(f"[CMD] {' '.join(cmd)} -> exit {result.returncode}", flush=True)
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    if result.stderr.strip():
        print(result.stderr.strip(), flush=True)
    return result


def run_deployment(file_name, current_time):
    with deploy_lock:
        time.sleep(3)
        safe_name = html.escape(file_name)
        notify(
            f"🚨 <b>NEW PDF DETECTED!</b>\n"
            f"📄 <b>File:</b> <code>{safe_name}</code>\n"
            f"⏰ <b>Time:</b> {current_time}\n\n"
            f"⚙️ <i>Initiating Ghost-Link Auto-Deploy...</i>"
        )

        try:
            r = run_cmd(["pwsh", "-ExecutionPolicy", "Bypass", "-File", "nexus_builder.ps1"])
            if r.returncode != 0:
                raise RuntimeError(f"nexus_builder.ps1 failed:\n{r.stderr or r.stdout}")

            r = run_cmd(["git", "add", "--all"])
            if r.returncode != 0:
                raise RuntimeError(f"git add failed:\n{r.stderr}")

            run_cmd(["git", "commit", "-m", f"⚡ Auto-sync: {file_name}"])

            r = run_cmd(["git", "pull", "origin", "main", "--no-edit"])
            if r.returncode != 0:
                raise RuntimeError(f"git pull failed:\n{r.stderr}")

            r = run_cmd(["git", "push"])
            if r.returncode != 0:
                raise RuntimeError(f"git push failed:\n{r.stderr}")

            notify(
                f"✅ <b>DEPLOYMENT COMPLETE!</b> 🚀\n"
                f"<code>{safe_name}</code> is live on your website."
            )
        except Exception as e:
            err_msg = html.escape(str(e)[:3000])
            notify(f"❌ <b>DEPLOYMENT FAILED:</b>\n<code>{err_msg}</code>")


class VaultWatcher(FileSystemEventHandler):
    def _trigger(self, path):
        if path.lower().endswith('.pdf'):
            file_name = os.path.basename(path)
            current_time = datetime.now().strftime("%I:%M:%S %p | %b %d, %Y")
            print(f"[WATCHDOG] Triggered for: {file_name}", flush=True)
            threading.Thread(
                target=run_deployment,
                args=(file_name, current_time),
                daemon=True
            ).start()

    def on_created(self, event):
        if not event.is_directory:
            self._trigger(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._trigger(event.dest_path)


@bot.message_handler(commands=['start'])
def activate_watchdog(message):
    save_chat_id(message.chat.id)
    bot.send_message(
        CHAT_ID,
        "🐕 <b>GHOST WATCHDOG ONLINE &amp; PERMANENTLY LOCKED!</b>\n"
        "Chat ID saved to disk. Drop a PDF or send /sync anytime.",
        parse_mode="HTML"
    )


@bot.message_handler(commands=['status'])
def check_status(message):
    if not CHAT_ID:
        save_chat_id(message.chat.id)
    bot.reply_to(message, f"✅ Watchdog alive.\nSaved CHAT_ID: <code>{CHAT_ID}</code>", parse_mode="HTML")


@bot.message_handler(commands=['sync'])
def manual_sync(message):
    if not CHAT_ID:
        save_chat_id(message.chat.id)
    current_time = datetime.now().strftime("%I:%M:%S %p | %b %d, %Y")
    threading.Thread(
        target=run_deployment,
        args=("Manual Telegram Sync", current_time),
        daemon=True
    ).start()


print(f"[SYSTEM] AUTONOMOUS WATCHDOG DEPLOYER ONLINE 🚀🐕 (Saved CHAT_ID: {CHAT_ID})", flush=True)
observer = Observer()
observer.schedule(VaultWatcher(), path=VAULT_PATH, recursive=True)
observer.start()

while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except Exception as e:
        print(f"[POLLING RESTART] {e}", flush=True)
        time.sleep(5)
