import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import subprocess
import urllib.parse
import threading

TOKEN = '8502180589:AAF8jg-0u7qWH8tUcb0FF8wWczDz5ZtrztQ'
VAULT_PATH = '/home/tejas/Project Nexus PDF version'
BASE_WEB_IP = 'https://2af8e2411286c9.lhr.life'

# Boot up the multi-threaded Bot Engine 🏎️
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20)

# Memory Maps to completely bypass Telegram's 64-byte limit 🧠
path_to_id = {}
id_to_path = {}
next_id = 1
user_page = {}
pending_uploads = {}

def get_path_id(full_path):
    global next_id
    clean = full_path.rstrip('/\\')
    if clean in path_to_id: return path_to_id[clean]
    pid = str(next_id)
    next_id += 1
    path_to_id[clean] = pid
    id_to_path[pid] = clean
    return pid

def get_clean_items(folder_path):
    ignore_folders = {".git", ".netlify", ".vscode", "node_modules"}
    ignore_exts = {".ps1", ".bat", ".html", ".js", ".vbs", ".sh", ".py"}
    ignore_names = {".gitignore", "phantom_bot.ps1", "phantom.py"}
    folders, files = [], []
    try:
        for item in sorted(os.listdir(folder_path)):
            if item.startswith('.'): continue
            full_path = os.path.join(folder_path, item)
            if os.path.isdir(full_path) and item not in ignore_folders:
                folders.append(item)
            elif os.path.isfile(full_path):
                ext = os.path.splitext(item)[1].lower()
                if ext not in ignore_exts and item.lower() not in ignore_names:
                    files.append(item)
    except: pass
    return folders, files

def send_vault_menu(chat_id, folder_path, message_id=None):
    if not os.path.exists(folder_path): return
    clean_current = folder_path.rstrip('/\\')
    clean_root = VAULT_PATH.rstrip('/\\')
    current_id = get_path_id(clean_current)
    root_id = get_path_id(clean_root)
    
    folders, files = get_clean_items(clean_current)
    all_items = [('D', f) for f in folders] + [('F', f) for f in files]
    
    # 💥 THE LIMIT DESTROYER (Smart Pagination) 💥
    ITEMS_PER_PAGE = 30
    total_pages = max(1, (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = user_page.get(chat_id, 0)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ITEMS_PER_PAGE
    page_items = all_items[start_idx : start_idx + ITEMS_PER_PAGE]
    
    markup = InlineKeyboardMarkup(row_width=1)
    
    for item_type, item_name in page_items:
        full_path = os.path.join(clean_current, item_name)
        pid = get_path_id(full_path)
        icon = "📁" if item_type == 'D' else "📄"
        markup.add(InlineKeyboardButton(f"{icon} {item_name}", callback_data=f"{item_type}:{pid}"))
        
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️ Prev Page", callback_data=f"P:{current_id}:{page-1}"))
    if page < total_pages - 1: nav_buttons.append(InlineKeyboardButton("Next Page ➡️", callback_data=f"P:{current_id}:{page+1}"))
    if nav_buttons: markup.row(*nav_buttons)
        
    if clean_current != clean_root:
        parent_id = get_path_id(os.path.dirname(clean_current))
        markup.row(
            InlineKeyboardButton("⬅️ BACK", callback_data=f"D:{parent_id}"),
            InlineKeyboardButton("🏠 MAIN VAULT", callback_data=f"D:{root_id}")
        )
        
    if chat_id in pending_uploads:
        markup.add(InlineKeyboardButton("✅ DROP FILE IN THIS FOLDER", callback_data=f"SAVE:{current_id}"))
        msg_text = f"⚠️ <b>PENDING UPLOAD DETECTED</b>\n📍 <code>{clean_current}</code>"
    else:
        markup.add(InlineKeyboardButton("🔄 REFRESH LIVE", callback_data=f"D:{current_id}"))
        msg_text = f"⚡ <b>SECTOR:</b> <code>{clean_current}</code>\n<i>Page {page+1} of {total_pages}</i>"
        
    try:
        if message_id: bot.edit_message_text(msg_text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
        else: bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")
    except: pass

@bot.message_handler(commands=['vault', 'start'])
def handle_vault(message):
    user_page[message.chat.id] = 0
    if message.chat.id in pending_uploads: del pending_uploads[message.chat.id]
    send_vault_menu(message.chat.id, VAULT_PATH)

@bot.message_handler(content_types=['document', 'photo'])
def handle_docs(message):
    chat_id = message.chat.id
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "Upload.pdf"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "Photo.jpg"
    pending_uploads[chat_id] = {"id": file_id, "name": file_name}
    user_page[chat_id] = 0
    send_vault_menu(chat_id, VAULT_PATH)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    bot.answer_callback_query(call.id) # ZERO LATENCY ACKNOWLEDGMENT ⚡
    
    if data.startswith("D:"):
        pid = data.split(":")[1]
        path = id_to_path.get(pid)
        if path:
            user_page[chat_id] = 0 
            send_vault_menu(chat_id, path, msg_id)
            
    elif data.startswith("P:"):
        _, pid, page_str = data.split(":")
        path = id_to_path.get(pid)
        if path:
            user_page[chat_id] = int(page_str)
            send_vault_menu(chat_id, path, msg_id)
            
    elif data.startswith("F:"):
        pid = data.split(":")[1]
        path = id_to_path.get(pid)
        if path and os.path.exists(path):
            bot.send_message(chat_id, "📡 Beaming file to you...")
            threading.Thread(target=lambda: bot.send_document(chat_id, open(path, 'rb'))).start()
            
    elif data.startswith("SAVE:"):
        pid = data.split(":")[1]
        path = id_to_path.get(pid)
        if path and chat_id in pending_uploads:
            file_info = pending_uploads.pop(chat_id)
            bot.edit_message_text("🚀 <b>Downloading directly to Dell Server...</b>", chat_id, msg_id, parse_mode="HTML")
            threading.Thread(target=process_download, args=(chat_id, path, file_info)).start()
            send_vault_menu(chat_id, path)

def process_download(chat_id, folder_path, file_info):
    try:
        file_id = file_info["id"]
        raw_name = file_info["name"]
        file_obj = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_obj.file_path)
        
        clean_name = raw_name.replace("|", "-").replace(":", "")
        dest_path = os.path.join(folder_path, clean_name)
        with open(dest_path, 'wb') as f: f.write(downloaded_file)
            
        ext = os.path.splitext(clean_name)[1].lower()
        if ext in ['.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx']:
            bot.send_message(chat_id, "⚙️ <b>Converting document to PDF in background...</b>", parse_mode="HTML")
            subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", dest_path, "--outdir", folder_path])
            pdf_name = os.path.splitext(clean_name)[0] + '.pdf'
            dest_path = os.path.join(folder_path, pdf_name)
            clean_name = pdf_name
            
        if os.path.exists(dest_path):
            rel_path = dest_path.replace(VAULT_PATH, "").replace("\\", "/").lstrip("/")
            safe_url = BASE_WEB_IP + "/" + urllib.parse.quote(rel_path)
            msg = f"✅ <b>UPLOAD & SYNC SUCCESSFUL</b>\n<code>{clean_name}</code>\n\n🌐 <b>Check your website:</b>\n<a href='{safe_url}'>{safe_url}</a>"
            bot.send_message(chat_id, msg, parse_mode="HTML", disable_web_page_preview=True)
    except: pass

print("[SYSTEM] PYTHON PENTA-ENGINE ACTIVE ON LINUX 🚀🐍")
bot.set_my_commands([telebot.types.BotCommand("/vault", "📂 Open Nexus Vault")])
bot.infinity_polling(timeout=10, long_polling_timeout=5)