import telebot
import subprocess
import os
import time
from datetime import datetime
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

TOKEN = '9175870752:AAEMoJlKbvID_ENKj9YvZ5JRM2Y2qV46V2g'
VAULT_PATH = '/home/tejas/Project Nexus PDF version'
CHAT_ID = None  # Locks onto your chat when you send /start

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=10)

class VaultWatcher(FileSystemEventHandler):
    def on_created(self, event):
        # Only trigger when a new PDF drops, ignoring HTML or Git background files
        if not event.is_directory and event.src_path.lower().endswith('.pdf'):
            if CHAT_ID:
                file_name = os.path.basename(event.src_path)
                current_time = datetime.now().strftime("%I:%M:%S %p | %b %d, %Y")
                # Spin up a background thread so the watcher never freezes
                threading.Thread(target=run_deployment, args=(file_name, current_time)).start()

def run_deployment(file_name, current_time):
    time.sleep(2) # Give the Phantom bot 2 seconds to completely finish writing the file
    bot.send_message(CHAT_ID, f"🚨 <b>NEW PDF DETECTED!</b>\n📄 <b>File:</b> <code>{file_name}</code>\n⏰ <b>Time:</b> {current_time}\n\n⚙️ <i>Initiating Ghost-Link Auto-Deploy...</i>", parse_mode="HTML")
    
    try:
        subprocess.run(["pwsh", "-ExecutionPolicy", "Bypass", "-File", "nexus_builder.ps1"], cwd=VAULT_PATH, check=True)
        subprocess.run(["git", "add", "--all"], cwd=VAULT_PATH, check=True)
        subprocess.run(["git", "commit", "-m", f"⚡ Auto-sync: {file_name}"], cwd=VAULT_PATH)
        subprocess.run(["git", "pull", "origin", "main", "--no-edit"], cwd=VAULT_PATH)
        subprocess.run(["git", "push"], cwd=VAULT_PATH, check=True)
        
        bot.send_message(CHAT_ID, f"✅ <b>DEPLOYMENT COMPLETE!</b> 🚀\n<code>{file_name}</code> is live on your website.", parse_mode="HTML")
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ <b>DEPLOYMENT FAILED:</b>\n<code>{str(e)}</code>", parse_mode="HTML")

@bot.message_handler(commands=['start'])
def activate_watchdog(message):
    global CHAT_ID
    CHAT_ID = message.chat.id
    bot.send_message(CHAT_ID, "🐕 <b>GHOST WATCHDOG ONLINE & LOCKED!</b>\nI am monitoring your server 24/7. Drop a PDF into your Phantom Bot and I will automatically catch it, log the time, and push it to GitHub.", parse_mode="HTML")

print("[SYSTEM] AUTONOMOUS WATCHDOG DEPLOYER ONLINE 🚀🐕")
observer = Observer()
observer.schedule(VaultWatcher(), path=VAULT_PATH, recursive=True)
observer.start()

bot.infinity_polling(timeout=20, long_polling_timeout=15)