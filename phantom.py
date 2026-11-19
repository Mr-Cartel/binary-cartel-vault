import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from concurrent.futures import ThreadPoolExecutor
import os
import shutil
import subprocess
import time
import html
import threading

TOKEN = '8502180589:AAF8jg-0u7qWH8tUcb0FF8wWczDz5ZtrztQ'
VAULT_PATH = '/home/tejas/Project Nexus PDF version'
CLEAN_ROOT = VAULT_PATH.rstrip('/\\')
REAL_ROOT = os.path.realpath(CLEAN_ROOT)

# Keep HTTPS connections warm to cut Telegram API latency ⚡
apihelper.SESSION_TIME_TO_LIVE = 300

# Pre-warmed worker pool & multi-threaded Bot Engine 🏎️
executor = ThreadPoolExecutor(max_workers=24)
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20)

# Static filter sets (allocated once, never rebuilt per click)
IGNORE_FOLDERS = {".git", ".netlify", ".vscode", "node_modules"}
IGNORE_EXTS = {".ps1", ".bat", ".html", ".js", ".vbs", ".sh", ".py"}
IGNORE_NAMES = {".gitignore", "phantom_bot.ps1", "phantom.py", "deployer.py", "watchdog_chat_id.txt"}

# High-speed in-memory maps & caches 🧠
id_lock = threading.Lock()
sync_lock = threading.Lock()
index_lock = threading.Lock()

path_to_id = {}
id_to_path = {}
next_id = 1

dir_cache = {}       # folder_path -> (mtime, folders, files)
file_id_cache = {}   # file_path -> (mtime, telegram_file_id)
pdf_index = []       # list of (search_blob, file_name, rel_folder, full_path)
last_index_time = 0.0

user_page = {}
user_search = {}     # chat_id -> (query, results, elapsed_ms)
pending_uploads = {}
pending_mkdir = {}
pending_search = set()
delete_mode = {}


def get_path_id(full_path):
    global next_id
    clean = full_path.rstrip('/\\')
    pid = path_to_id.get(clean)
    if pid is not None:
        return pid
    with id_lock:
        pid = path_to_id.get(clean)
        if pid is not None:
            return pid
        pid = str(next_id)
        next_id += 1
        path_to_id[clean] = pid
        id_to_path[pid] = clean
        return pid


def is_safe_subpath(target_path):
    """Ensure target is strictly inside VAULT_PATH and is never the root vault itself."""
    try:
        real_target = os.path.realpath(target_path)
        return os.path.commonpath([REAL_ROOT, real_target]) == REAL_ROOT and real_target != REAL_ROOT
    except Exception:
        return False


def fast_ack(call_id):
    try:
        bot.answer_callback_query(call_id)
    except Exception:
        pass


def rebuild_pdf_index():
    """Fast stack-based os.scandir() index of every PDF across all subfolders."""
    global pdf_index, last_index_time
    new_index = []
    stack = [CLEAN_ROOT]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    name = entry.name
                    if name.startswith('.'):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if name not in IGNORE_FOLDERS:
                            stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and name.lower().endswith('.pdf'):
                        rel_dir = os.path.relpath(current, CLEAN_ROOT)
                        rel_label = "" if rel_dir == "." else rel_dir
                        blob = f"{rel_label}/{name}".lower()
                        new_index.append((blob, name, rel_label, entry.path))
        except Exception:
            continue

    new_index.sort(key=lambda item: item[1].lower())
    with index_lock:
        pdf_index = new_index
        last_index_time = time.time()


def invalidate_pdf_index():
    global last_index_time
    last_index_time = 0.0
    executor.submit(rebuild_pdf_index)


def search_pdfs(query):
    """Sub-millisecond multi-word search across the RAM index."""
    if not pdf_index or (time.time() - last_index_time) > 60:
        rebuild_pdf_index()

    t0 = time.perf_counter()
    terms = query.lower().split()
    if not terms:
        return [], 0.0

    with index_lock:
        snapshot = pdf_index

    matches = []
    for blob, name, rel_label, full_path in snapshot:
        if all(t in blob for t in terms):
            lname = name.lower()
            # Rank: 0 = filename starts with first term, 1 = all terms in filename, 2 = matched via folder + filename
            if lname.startswith(terms[0]):
                rank = 0
            elif all(t in lname for t in terms):
                rank = 1
            else:
                rank = 2
            matches.append((rank, name, rel_label, full_path))

    matches.sort(key=lambda x: (x[0], x[1].lower()))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return matches, elapsed_ms


def send_search_results(chat_id, query, matches, elapsed_ms, page=0, message_id=None):
    ITEMS_PER_PAGE = 15
    total = len(matches)
    safe_query = html.escape(query)
    root_id = get_path_id(CLEAN_ROOT)

    if total == 0:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📂 OPEN MAIN VAULT", callback_data=f"D:{root_id}"))
        text = (
            f"🔍 <b>SEARCH:</b> <code>{safe_query}</code>\n"
            f"❌ No matching PDFs found. <i>({elapsed_ms:.2f} ms)</i>"
        )
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        return

    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE
    page_items = matches[start: start + ITEMS_PER_PAGE]

    markup = InlineKeyboardMarkup(row_width=1)
    for _, name, rel_label, full_path in page_items:
        pid = get_path_id(full_path)
        short_folder = os.path.basename(rel_label) if rel_label else "Root"
        label = f"📄 {name}  [{short_folder}]"
        if len(label) > 60:
            label = f"📄 {name[:42]}… [{short_folder[:12]}]"
        markup.add(InlineKeyboardButton(label, callback_data=f"F:{pid}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"SP:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"SP:{page + 1}"))
    if nav:
        markup.row(*nav)

    markup.add(InlineKeyboardButton("📂 OPEN MAIN VAULT", callback_data=f"D:{root_id}"))

    text = (
        f"🔍 <b>RESULTS FOR:</b> <code>{safe_query}</code>\n"
        f"⚡ Found <b>{total}</b> PDF{'s' if total != 1 else ''} in <b>{elapsed_ms:.2f} ms</b> "
        f"<i>(Page {page + 1}/{total_pages})</i>\n"
        f"<i>Tap any PDF to beam it instantly:</i>"
    )
    try:
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass


def get_clean_items(folder_path, force_refresh=False):
    try:
        mtime = os.path.getmtime(folder_path)
        cached = dir_cache.get(folder_path)
        if not force_refresh and cached and cached[0] == mtime:
            return cached[1], cached[2]

        folders, files = [], []
        with os.scandir(folder_path) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith('.'):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if name not in IGNORE_FOLDERS:
                        folders.append(name)
                elif entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in IGNORE_EXTS and name.lower() not in IGNORE_NAMES:
                        files.append(name)

        folders.sort()
        files.sort()
        dir_cache[folder_path] = (mtime, folders, files)
        return folders, files
    except Exception:
        return [], []


def send_vault_menu(chat_id, folder_path, message_id=None, force_refresh=False):
    if not os.path.exists(folder_path):
        folder_path = CLEAN_ROOT

    clean_current = folder_path.rstrip('/\\')
    current_id = get_path_id(clean_current)
    root_id = get_path_id(CLEAN_ROOT)
    in_delete_mode = delete_mode.get(chat_id, False)

    folders, files = get_clean_items(clean_current, force_refresh=force_refresh)
    all_items = [('D', f) for f in folders] + [('F', f) for f in files]

    # 💥 THE LIMIT DESTROYER (Smart Pagination) 💥
    ITEMS_PER_PAGE = 30
    total_pages = max(1, (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(user_page.get(chat_id, 0), total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    page_items = all_items[start_idx: start_idx + ITEMS_PER_PAGE]

    markup = InlineKeyboardMarkup(row_width=1)

    for item_type, item_name in page_items:
        full_path = os.path.join(clean_current, item_name)
        pid = get_path_id(full_path)
        icon = "📁" if item_type == 'D' else "📄"
        if in_delete_mode:
            markup.add(InlineKeyboardButton(f"🗑️ {icon} {item_name}", callback_data=f"DELASK:{pid}"))
        else:
            markup.add(InlineKeyboardButton(f"{icon} {item_name}", callback_data=f"{item_type}:{pid}"))

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev Page", callback_data=f"P:{current_id}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next Page ➡️", callback_data=f"P:{current_id}:{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    if clean_current != CLEAN_ROOT:
        parent_id = get_path_id(os.path.dirname(clean_current))
        markup.row(
            InlineKeyboardButton("⬅️ BACK", callback_data=f"D:{parent_id}"),
            InlineKeyboardButton("🏠 MAIN VAULT", callback_data=f"D:{root_id}")
        )

    safe_current = html.escape(clean_current)

    if chat_id in pending_uploads:
        markup.row(
            InlineKeyboardButton("✅ DROP FILE HERE", callback_data=f"SAVE:{current_id}"),
            InlineKeyboardButton("➕ NEW FOLDER", callback_data=f"MKDIR:{current_id}")
        )
        msg_text = (
            f"⚠️ <b>PENDING UPLOAD DETECTED</b>\n"
            f"📍 <code>{safe_current}</code>\n"
            f"<i>Navigate or create a folder, then tap Drop File Here.</i>"
        )
    elif in_delete_mode:
        markup.row(
            InlineKeyboardButton("❌ EXIT DELETE MODE", callback_data=f"DELMODE:{current_id}"),
            InlineKeyboardButton("🔄 REFRESH", callback_data=f"R:{current_id}")
        )
        msg_text = (
            f"🚨 <b>DELETE MODE ACTIVE</b>\n"
            f"📍 <code>{safe_current}</code>\n"
            f"<i>Tap any file or folder above to delete it. (Page {page+1}/{total_pages})</i>"
        )
    else:
        markup.row(
            InlineKeyboardButton("➕ NEW FOLDER", callback_data=f"MKDIR:{current_id}"),
            InlineKeyboardButton("🗑️ DELETE MODE", callback_data=f"DELMODE:{current_id}")
        )
        markup.add(InlineKeyboardButton("🔄 REFRESH LIVE", callback_data=f"R:{current_id}"))
        msg_text = f"⚡ <b>SECTOR:</b> <code>{safe_current}</code>\n<i>Page {page+1} of {total_pages}</i>"

    try:
        if message_id:
            bot.edit_message_text(msg_text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass


@bot.message_handler(commands=['vault', 'start'])
def handle_vault(message):
    chat_id = message.chat.id
    user_page[chat_id] = 0
    delete_mode[chat_id] = False
    pending_uploads.pop(chat_id, None)
    pending_mkdir.pop(chat_id, None)
    pending_search.discard(chat_id)
    send_vault_menu(chat_id, CLEAN_ROOT)


@bot.message_handler(commands=['find'])
def handle_find(message):
    chat_id = message.chat.id
    pending_mkdir.pop(chat_id, None)
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        pending_search.add(chat_id)
        bot.reply_to(
            message,
            "🔍 <b>INSTANT PDF SEARCH</b>\nType keywords to search across all folders (e.g. <code>chem gas</code> or <code>unit pyq</code>), or /cancel:",
            parse_mode="HTML"
        )
        return

    pending_search.discard(chat_id)
    query = parts[1].strip()
    matches, elapsed_ms = search_pdfs(query)
    user_search[chat_id] = (query, matches, elapsed_ms)
    send_search_results(chat_id, query, matches, elapsed_ms, page=0)


@bot.message_handler(commands=['cancel'])
def handle_cancel(message):
    chat_id = message.chat.id
    pending_uploads.pop(chat_id, None)
    pending_mkdir.pop(chat_id, None)
    pending_search.discard(chat_id)
    delete_mode[chat_id] = False
    bot.reply_to(message, "✅ Cancelled current action.")
    send_vault_menu(chat_id, CLEAN_ROOT)


@bot.message_handler(content_types=['document', 'photo'])
def handle_docs(message):
    chat_id = message.chat.id
    delete_mode[chat_id] = False
    pending_mkdir.pop(chat_id, None)
    pending_search.discard(chat_id)
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "Upload.pdf"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "Photo.jpg"
    pending_uploads[chat_id] = {"id": file_id, "name": file_name}
    user_page[chat_id] = 0
    send_vault_menu(chat_id, CLEAN_ROOT)


def send_file_worker(chat_id, path):
    try:
        mtime = os.path.getmtime(path)
        cached = file_id_cache.get(path)
        if cached and cached[0] == mtime:
            bot.send_document(chat_id, cached[1])
            return

        bot.send_message(chat_id, "📡 Beaming file to you...")
        with open(path, 'rb') as f:
            sent = bot.send_document(chat_id, f)
        if sent and sent.document:
            file_id_cache[path] = (mtime, sent.document.file_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>Failed to send file:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    executor.submit(fast_ack, call.id)

    if data.startswith("D:"):
        path = id_to_path.get(data[2:])
        if path:
            user_page[chat_id] = 0
            send_vault_menu(chat_id, path, msg_id)

    elif data.startswith("R:"):
        path = id_to_path.get(data[2:])
        if path:
            invalidate_pdf_index()
            send_vault_menu(chat_id, path, msg_id, force_refresh=True)

    elif data.startswith("P:"):
        _, pid, page_str = data.split(":")
        path = id_to_path.get(pid)
        if path:
            user_page[chat_id] = int(page_str)
            send_vault_menu(chat_id, path, msg_id)

    elif data.startswith("SP:"):
        saved = user_search.get(chat_id)
        if saved:
            query, matches, elapsed_ms = saved
            send_search_results(chat_id, query, matches, elapsed_ms, page=int(data[3:]), message_id=msg_id)

    elif data.startswith("F:"):
        path = id_to_path.get(data[2:])
        if path and os.path.exists(path):
            executor.submit(send_file_worker, chat_id, path)

    elif data.startswith("SAVE:"):
        path = id_to_path.get(data[5:])
        if path and chat_id in pending_uploads:
            file_info = pending_uploads.pop(chat_id)
            bot.edit_message_text("🚀 <b>Downloading directly to Snowy...</b>", chat_id, msg_id, parse_mode="HTML")
            executor.submit(process_download, chat_id, path, file_info)
            send_vault_menu(chat_id, path)

    elif data.startswith("MKDIR:"):
        path = id_to_path.get(data[6:])
        if path and os.path.isdir(path):
            delete_mode[chat_id] = False
            pending_search.discard(chat_id)
            pending_mkdir[chat_id] = path
            bot.send_message(
                chat_id,
                f"📁 <b>CREATE NEW FOLDER</b>\n"
                f"📍 Inside: <code>{html.escape(path)}</code>\n\n"
                f"Type the folder name now (or send /cancel):",
                parse_mode="HTML"
            )

    elif data.startswith("DELMODE:"):
        path = id_to_path.get(data[8:])
        if path:
            delete_mode[chat_id] = not delete_mode.get(chat_id, False)
            send_vault_menu(chat_id, path, msg_id)

    elif data.startswith("DELASK:"):
        pid = data[7:]
        path = id_to_path.get(pid)
        if not path or not os.path.exists(path) or not is_safe_subpath(path):
            bot.send_message(chat_id, "⚠️ Item not found or protected.")
            return
        parent_id = get_path_id(os.path.dirname(path))
        item_type = "FOLDER (and everything inside it!)" if os.path.isdir(path) else "FILE"
        item_name = html.escape(os.path.basename(path))
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ YES, DELETE", callback_data=f"DELYES:{pid}"),
            InlineKeyboardButton("❌ CANCEL", callback_data=f"DELNO:{parent_id}")
        )
        bot.edit_message_text(
            f"⚠️ <b>CONFIRM PERMANENT DELETE</b>\n\n"
            f"Type: <b>{item_type}</b>\n"
            f"Target: <code>{item_name}</code>",
            chat_id,
            msg_id,
            reply_markup=markup,
            parse_mode="HTML"
        )

    elif data.startswith("DELNO:"):
        parent_path = id_to_path.get(data[6:], CLEAN_ROOT)
        send_vault_menu(chat_id, parent_path, msg_id)

    elif data.startswith("DELYES:"):
        path = id_to_path.get(data[7:])
        if not path or not os.path.exists(path) or not is_safe_subpath(path):
            bot.edit_message_text("⚠️ Already deleted or protected.", chat_id, msg_id)
            return

        parent_path = os.path.dirname(path)
        item_name = html.escape(os.path.basename(path))
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            dir_cache.pop(parent_path, None)
            dir_cache.pop(path, None)
            file_id_cache.pop(path, None)
            invalidate_pdf_index()
            bot.send_message(
                chat_id,
                f"🗑️ <b>DELETED:</b> <code>{item_name}</code>\n"
                f"<i>Tip: Send /pikachu when ready to remove it from the live website too.</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            bot.send_message(chat_id, f"❌ <b>DELETE FAILED:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")

        send_vault_menu(chat_id, parent_path, msg_id, force_refresh=True)


def process_download(chat_id, folder_path, file_info):
    try:
        file_id = file_info["id"]
        raw_name = file_info["name"]
        file_obj = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_obj.file_path)

        clean_name = raw_name.replace("|", "-").replace(":", "").replace("/", "-").replace("\\", "-")
        dest_path = os.path.join(folder_path, clean_name)
        with open(dest_path, 'wb') as f:
            f.write(downloaded_file)

        ext = os.path.splitext(clean_name)[1].lower()
        if ext in ['.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx']:
            bot.send_message(chat_id, "⚙️ <b>Converting document to PDF in background...</b>", parse_mode="HTML")
            subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", dest_path, "--outdir", folder_path])
            pdf_name = os.path.splitext(clean_name)[0] + '.pdf'
            dest_path = os.path.join(folder_path, pdf_name)
            clean_name = pdf_name

        dir_cache.pop(folder_path, None)
        invalidate_pdf_index()

        if os.path.exists(dest_path):
            rel_path = os.path.relpath(dest_path, CLEAN_ROOT)
            msg = (
                f"✅ <b>SAVED TO SNOWY!</b>\n"
                f"📄 <code>{html.escape(clean_name)}</code>\n"
                f"📁 <code>{html.escape(rel_path)}</code>\n\n"
                f"🐕 <i>Watchdog will auto-sync PDFs, or send /pikachu to push now.</i>"
            )
            bot.send_message(chat_id, msg, parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>UPLOAD FAILED:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")


def run_pikachu_sync(chat_id):
    with sync_lock:
        try:
            r = subprocess.run(["pwsh", "-ExecutionPolicy", "Bypass", "-File", "nexus_builder.ps1"], cwd=CLEAN_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr or r.stdout)

            r = subprocess.run(["git", "add", "--all"], cwd=CLEAN_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr)

            subprocess.run(["git", "commit", "-m", "⚡ Auto-sync from Telegram Bot"], cwd=CLEAN_ROOT, capture_output=True, text=True)

            r = subprocess.run(["git", "pull", "origin", "main", "--no-edit"], cwd=CLEAN_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr)

            r = subprocess.run(["git", "push"], cwd=CLEAN_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr)

            bot.send_message(chat_id, "✅ <b>SYNC COMPLETE!</b>\nYour Binary Cartel HTML buttons are updating now. 🚀", parse_mode="HTML")
        except Exception as e:
            bot.send_message(chat_id, f"❌ <b>SYNC FAILED:</b>\n<code>{html.escape(str(e)[:3000])}</code>", parse_mode="HTML")


@bot.message_handler(commands=['pikachu'])
def handle_github_sync(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⚡ <b>PIKACHU!</b> Initiating HTML Build &amp; GitHub Sync...", parse_mode="HTML")
    executor.submit(run_pikachu_sync, chat_id)


@bot.message_handler(func=lambda m: m.chat.id in pending_search and bool(m.text) and not m.text.startswith('/'))
def handle_search_input(message):
    chat_id = message.chat.id
    pending_search.discard(chat_id)
    query = message.text.strip()
    matches, elapsed_ms = search_pdfs(query)
    user_search[chat_id] = (query, matches, elapsed_ms)
    send_search_results(chat_id, query, matches, elapsed_ms, page=0)


@bot.message_handler(func=lambda m: m.chat.id in pending_mkdir and bool(m.text) and not m.text.startswith('/'))
def handle_mkdir_name(message):
    chat_id = message.chat.id
    parent_path = pending_mkdir.pop(chat_id)
    folder_name = message.text.strip()

    if not folder_name or folder_name.startswith('.') or any(ch in folder_name for ch in ['/', '\\', '..', '\x00']):
        bot.reply_to(message, "⚠️ Invalid folder name. Avoid slashes or starting with a dot. Try again with ➕ NEW FOLDER.")
        return

    new_folder_path = os.path.join(parent_path, folder_name)
    if not is_safe_subpath(new_folder_path):
        bot.reply_to(message, "⚠️ Blocked unsafe folder path.")
        return

    try:
        os.makedirs(new_folder_path, exist_ok=True)
        with open(os.path.join(new_folder_path, ".gitkeep"), "a"):
            pass
        dir_cache.pop(parent_path, None)
        bot.reply_to(
            message,
            f"✅ <b>EMPTY FOLDER CREATED!</b>\n📁 <code>{html.escape(folder_name)}</code>",
            parse_mode="HTML"
        )
        send_vault_menu(chat_id, parent_path, force_refresh=True)
    except Exception as e:
        bot.reply_to(message, f"❌ <b>FAILED TO CREATE FOLDER:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")


# Pre-warm the PDF search index in RAM on boot 🚀
rebuild_pdf_index()
print(f"[SYSTEM] PYTHON PENTA-ENGINE TURBO + SEARCH ACTIVE 🚀🐍 ({len(pdf_index)} PDFs indexed)", flush=True)

bot.set_my_commands([
    telebot.types.BotCommand("/vault", "📂 Open Nexus Vault"),
    telebot.types.BotCommand("/find", "🔍 Instant PDF Search"),
    telebot.types.BotCommand("/pikachu", "⚡ Sync Website"),
    telebot.types.BotCommand("/cancel", "❌ Cancel Current Action")
])

while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        print(f"[POLLING RESTART] {e}", flush=True)
        time.sleep(3)
