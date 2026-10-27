import telebot
import subprocess
import os
import threading

TOKEN = '9175870752:AAEMoJlKbvID_ENKj9YvZ5JRM2Y2qV46V2g'
VAULT_PATH = '/home/tejas/Project Nexus PDF version'

# Boot up the Dedicated Deployer Engine 🏎️☁️
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=10)

def run_deployment(chat_id):
    try:
        bot.send_message(chat_id, "⚙️ <b>STEP 1/3: Rebuilding HTML Buttons...</b>\n<i>Running nexus_builder.ps1 via Linux PowerShell</i>", parse_mode="HTML")
        subprocess.run(["pwsh", "-ExecutionPolicy", "Bypass", "-File", "nexus_builder.ps1"], cwd=VAULT_PATH, check=True)
        
        bot.send_message(chat_id, "📦 <b>STEP 2/3: Packaging Files...</b>\n<i>Tracking new PDFs and HTML updates</i>", parse_mode="HTML")
        subprocess.run(["git", "add", "--all"], cwd=VAULT_PATH, check=True)
        subprocess.run(["git", "commit", "-m", "⚡ Live Deployment via Deployer Bot"], cwd=VAULT_PATH)
        
        bot.send_message(chat_id, "☁️ <b>STEP 3/3: Pushing to GitHub...</b>\n<i>Syncing cloud repository</i>", parse_mode="HTML")
        subprocess.run(["git", "pull", "origin", "main", "--no-edit"], cwd=VAULT_PATH)
        subprocess.run(["git", "push"], cwd=VAULT_PATH, check=True)
        
        bot.send_message(chat_id, "✅ <b>DEPLOYMENT COMPLETE!</b> 🚀\n\nYour Binary Kartal website is live. Press <b>Ctrl + Shift + R</b> on your browser to see the new glowing buttons!", parse_mode="HTML")
        
    except subprocess.CalledProcessError as e:
        bot.send_message(chat_id, f"❌ <b>DEPLOYMENT CRASHED:</b>\n<code>{str(e)}</code>", parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ <b>SYSTEM ERROR:</b>\n<code>{str(e)}</code>", parse_mode="HTML")

@bot.message_handler(commands=['deploy', 'pikachu', 'start'])
def handle_deploy(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⚡ <b>INITIATING GHOST-LINK DEPLOYMENT ENGINE...</b> ⚡", parse_mode="HTML")
    # Execute the heavy lifting in the background so the bot stays lightning fast! 🧠
    threading.Thread(target=run_deployment, args=(chat_id,)).start()

print("[SYSTEM] DEDICATED DEPLOYER BOT ONLINE 🚀☁️")
bot.set_my_commands([
    telebot.types.BotCommand("/deploy", "⚡ Launch Website Update")
])
bot.infinity_polling(timeout=20, long_polling_timeout=15)