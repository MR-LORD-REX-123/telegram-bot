import cloudscraper
from bs4 import BeautifulSoup
import requests
import img2pdf
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import logging
import threading
import asyncio
import json
import psutil
import aiohttp

api_id =""
scraper = cloudscraper.create_scraper()
page_limit=20
ADMIN=[5103772471]


# logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# main dowloader function
async def download_nhentai(code, update, context, chat_id,is_admin=False):
    page_num = 1
    last_page = await get_last_page(code)
    if last_page is None:
        await context.bot.send_message(chat_id=chat_id, text="❌ Could not find the manga.")
        return
    
    pages_size = last_page if is_admin else min(last_page, page_limit)
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [download_page(code, i, session) for i in range(1, pages_size + 1)]
        img_arr = await asyncio.gather(*tasks)
    logging.info(f"Downloaded {len(img_arr)} pages for code {code}")

    img_arr = [img for img in img_arr if img is not None]

    if not img_arr:
        await context.bot.send_message(chat_id=chat_id, text="❌ Failed to download any pages.")
        return

    os.makedirs('downloads', exist_ok=True)
    pdf_path = os.path.join('downloads', f"{code}.pdf")
    pdf_path = await create_pdf(img_arr, pdf_path)
    if pdf_path is None:
        logging.error("PDF creation failed.")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Failed to create PDF. Please try again with a different code."
        )
        return
    else:
        logging.info(f"PDF created successfully at {pdf_path}")
        with open(pdf_path, 'rb') as pdf_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=pdf_file,
                filename=f"{code}.pdf",
                caption="📄 Here is your PDF!"
            )
    try:
        os.remove(pdf_path)
        logging.info(f"Removed temporary PDF file: {pdf_path}")
    except Exception as e:
        logging.error(f"Error removing PDF file: {str(e)}") 
    
# download tread creation
def download_nhentai_thread(code, update, context):
    # Check if the user is an admin
    if str(update.effective_user.id) in map(str, ADMIN):
        is_admin = True
    else:
        is_admin = False
    try:
        chat_id = update.effective_chat.id
        logging.info(f"Starting download for code: {code}")

        # run inside thread but submit coroutine to bot's loop safely
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(download_nhentai(code, update, context, chat_id,is_admin), loop)

    except Exception as e:
        logging.error(f"Error starting thread: {e}")

# pdf creation 
async def create_pdf(imgs,pdf_path):
    try:
        with open(pdf_path, 'wb') as f:
            f.write(img2pdf.convert(imgs))
        logging.info(f"PDF created successfully at {pdf_path}")
    except Exception as e:
        logging.error(f"Error creating PDF: {e}")
        return None
    return pdf_path

async def get_last_page(code):
        try:
            response = scraper.get(f'https://nhentai.net/g/{code}/1')
            logging.info(f"Response status code: {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"Network error: {str(e)}")    
            return f"Network error: {str(e)}"
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            last_page_tag = soup.find('a', class_='last')
            last_page = int(last_page_tag.get('href').split('/')[-2])
            return last_page
        else:
            logging.error(f"Code {code} not found or access forbidden.")
            return None
    
async def get_img_link(code, page_num):
    try:
        response = scraper.get(f'https://nhentai.net/g/{code}/{page_num}')
        logging.info(f"Response status code: {response.status_code}")
    except requests.RequestException as e:
        logging.error(f"Network error: {str(e)}")    
        return f"Network error: {str(e)}"
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser') 
        img = soup.find('section', id='image-container').find('img').get('src')
        return img
    else:
        logging.error(f"Code {code} not found or access forbidden.")
        return None

async def get_images(page_num,img):
    try:
            async with aiohttp.ClientSession() as session:
                async with session.get(img) as img_file:
                    if img_file.status == 200:
                        img_content = await img_file.read()
                        logging.info(f"Downloaded image for page {page_num}")
                        return img_content
                    else:
                        logging.error(f"Failed to download image on page {page_num}: {img_file.status}")
    except requests.RequestException as e:
        logging.error(f"Error downloading image on page {page_num}: {str(e)}")
        with open('image.png', 'rb') as img_file:
            img_content = img_file.read()
            logging.info(f"errot downloading image on page {page_num}, using default image")
            return img_content

# helper to download one page (link + image)
async def download_page(code, page_num, session):
    try:
        img_link = await get_img_link(code, page_num)
        async with session.get(img_link) as img_file:
            if img_file.status == 200:
                return await img_file.read()
            else:
                logging.error(f"Failed to download image on page {page_num}: {img_file.status}")
                return None
    except Exception as e:
        logging.error(f"Error in download_page for {page_num}: {str(e)}")
        return None


# new user data storage
def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or "Unknown"
    time= update.message.date.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    
    with open('users.json', 'r') as f:
        users = json.load(f)
        if user_id not in users:
            new_user = {
                user_id: {
                    "username": username,
                    "time": time
                }
            }
            with open('users.json', 'w') as f:
                users.update(new_user)
                json.dump(users, f, indent=4)
        else:
            users[user_id]["time"] = time
            with open('users.json', 'w') as f:
                json.dump(users, f, indent=4)

# cover page creation
async def cover_page(code, update, context, msg_id=None): 
    result = {}
    cover_img=[]
    try:
        response = scraper.get(f'https://nhentai.net/g/{code}/')
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find('title').text.strip().split('»')[0]
            result['title'] = title
            cover_img = [requests.get(soup.find('div', id='cover').find('img', class_='lazyload').get('data-src')).content]
            try:
                info = soup.find('div', id='info-block').find('div',id='info').find('section', id='tags')
                info_divs=info.find_all('div', class_='tag-container')
                
                for div in info_divs:
            # Get the label like "Parodies", "Characters", "Tags"
                    label = div.contents[0].strip().lower().rstrip(':')
                    name= [a.find('span', class_='name').text.strip() for a in div.find_all('a', class_='tag')]
                    result[label] = name
                await cover_and_query(update, context, code, cover_img[0], result,msg_id=msg_id)    
            except Exception as e:
                print(f"Error extracting tags: {e}")
                result = {}
    except Exception as e:
        print(f"Error: {e}")
        result = {}

# Create cover page with the cover image and manga info and query user for confirmation
async def cover_and_query(update: Update, context: ContextTypes.DEFAULT_TYPE, code,img,data, msg_id=None):
    chat_id = update.effective_chat.id
    caption= (
        f"Title: {data.get('title', 'Unknown')}\n\n"
        f"tags: {', '.join(data.get('tags', []))}\n\n"
        f"language: {data.get('languages', 'Unknown')}\n\n"
        f"characters: {', '.join(data.get('characters', []))}\n\n"
        f"pages: {data['pages'][0]}\n"
    )
    keyboard= [
        [
            InlineKeyboardButton("Download", callback_data=f"start_{code}"),
            InlineKeyboardButton("Cancel", callback_data=f"cancel_{code}"),
        ]
    ] 
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=img,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        reply_to_message_id=msg_id if msg_id else None
    )

# progress function to track the download status
def get_progress_bar(done: int, total: int, length: int = 20) -> str:
    percent = int((done / total) * 100)
    filled = int(length * done // total)
    bar = '█' * filled + '░' * (length - filled)
    return f"Progress: [{bar}] {percent}%"

# search manga function
async def search_manga_fuction(update: Update, context: ContextTypes.DEFAULT_TYPE,format,page=1,msg_id=None):
    try:
        response = scraper.get(f'https://nhentai.net/search/?q={format}&page={page}')
        if response.status_code == 200:
            soup= BeautifulSoup(response.text, 'html.parser')
            results_found = soup.find('h1')
            div_data=soup.find_all('div', class_='index-container')
            div_data = div_data[0].find_all('div', class_='gallery')
            num=1
            result={}
            for item in div_data:
                title = item.find('div', class_='caption').text.strip()
                thumbnail_link = item.find('img',class_='lazyload')['data-src']
                code= item.find('a',class_='cover')['href'].split('/')[2]
                result[num] = {
                    'title': title,
                    'code': code,
                    'thumbnail_link': thumbnail_link
                }
                num += 1
            context.user_data['search_results'] = result
            context.user_data["msg_id"] = msg_id
            await cover_for_search(update,context,result,msg_id=msg_id)
    except requests.RequestException as e:
        logging.error(f"Network error: {str(e)}")
        return f"Network error: {str(e)}"        


# cover page creation for search results
async def cover_for_search(update, context, result,item_num=1,msg_id=None):
    try:
        code = result[item_num]['code']
        img = requests.get(result[item_num]['thumbnail_link']).content
        await search_query(update, context, img, result, item_num,msg_id=msg_id)
    except Exception as e:
        logging.error(f"Error processing item {item_num}: {e}")
        if msg_id:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Error processing item {item_num}. Please try again later.",
                reply_to_message_id=msg_id
            )
        
#  query for search results
async def search_query(update: Update, context: ContextTypes.DEFAULT_TYPE,img, data, item_num=1, msg_id=None):
    try:
        chat_id = update.effective_chat.id
        caption = (
            f"Title: {data[item_num]['title']}\n\n"
            f"Code: {data[item_num]['code']}\n\n")
        code= data[item_num]['code']
        keyboard = [
            [
                InlineKeyboardButton("select", callback_data=f"select-search_{code}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel-search_{code}"),
            ],[
                InlineKeyboardButton("Prev", callback_data=f"next_{code}_{item_num - 1}" if item_num > 1 else f"cancel-search_{code}"),
                InlineKeyboardButton("Next", callback_data=f"next_{code}_{item_num + 1}"),
            ]
        ]
        await context.bot.send_photo(
        chat_id=chat_id,
        photo=img,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        reply_to_message_id=msg_id if msg_id else None
        )
    except Exception as e: 
        logging.error(f"Error sending search query: {e}")
        
# <------------------------------------------- handlers -------------------------------------------------------------------------------------------------------->

# Callback query handler for search results navigation
async def search_query_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    result = context.user_data.get('search_results', {})
    parts = data.split("_")
    action = parts[0]
    msg_id = context.user_data.get("msg_id", None)
    
    if action == 'cancel-search':
        await query.message.delete()
        return
    
    code = parts[1]
    
    if action == 'select-search':
        await query.message.delete()
        try:
            await cover_page(code, update, context,msg_id=msg_id)
        except Exception as e:
            logging.error(f"Error processing code {code}: {e}")
            await update.message.reply_text(f"❌ Error processing code {code}. Please try again later.")
            return
    
    if action == 'next':
        logger.info(f"Next item requested")
        item_num = int(parts[2])
        try:
            if item_num > len(result):
                context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"No more items to display.",
                    reply_to_message_id=msg_id if msg_id else None
                )
                return
            await query.message.delete()
            await cover_for_search(update, context, result, item_num, msg_id=msg_id)
        except Exception as e:
            logging.error(f"Error processing next item {item_num}: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Error processing item {item_num}. Please try again later.",
                reply_to_message_id=query.message.message_id if query.message else None
            )
            return
    if action == 'prev':
        logger.info(f"Previous item requested")
        item_num = int(parts[2])
        try:
            if item_num < 1:
                context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"No previous items to display.",
                    reply_to_message_id=msg_id if msg_id else None)
                await query.message.delete()
                return
            await query.message.delete()
            await cover_for_search(update, context, result, item_num, msg_id=msg_id)
        except Exception as e:
            logging.error(f"Error processing previous item {item_num}: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Error processing item {item_num}. Please try again later.",
                reply_to_message_id=query.message.message_id if query.message else None
            )
            return

# get /random manga 
async def get_random_manga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = scraper.get('https://nhentai.net/random')
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            code = soup.find('h3', id='gallery_id').text.strip().split('#')[-1]
            try:
                await cover_page(code, update, context)
            except Exception as e:
                logging.error(f"Error processing code {code}: {e}")
                await update.message.reply_text(f"❌ Error processing code {code}. Please try again later.")
                return
    except requests.RequestException as e:
        logging.error(f"Network error: {str(e)}")
        return        
        
# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users(update, context)
    await update.message.reply_text("welcome ! use /get <code> to get the manga . \n"
                                    "Use /search <name or tag> to search for manga.\n"
                                    "You can also use /random to get a random manga.\n"
                                    f"There is {page_limit} pages limit .\n")

# /users command handler for admin
async def users_data_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id= str(update.effective_user.id)
    if user_id in map(str, ADMIN):
        with open('users.json', 'r') as f:
            users = json.load(f)
            user_data = "\n".join([f"{user_id}: @{data['username']}" for user_id, data in users.items()])
            await update.message.reply_text(f"past users:\n{user_data}")

# /status command handler for admin
async def server_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) in map(str, ADMIN):
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        total_memory = memory_info.total
        memory_used= memory_info.used
        memory_usage = (memory_used / total_memory) * 100
        disk_info = psutil.disk_usage('/')
        disk_usage = disk_info.percent
        status_message = (
            f"Server Status:\n"
            f"total Memory: {total_memory / (1024 ** 3):.2f} GB\n"
            f"Memory Used: {memory_used / (1024 ** 3):.2f} GB\n"
            f"Memory Usage: {memory_usage:.2f}%\n"
            f"CPU Usage: {cpu_usage}%\n"
            f"Disk Usage: {disk_usage}%"
        )
        await update.message.reply_text(status_message)

# /get command handler
async def get_manga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users(update, context)
    code= update.message.text.strip().split(' ')[-1]
    if not code.isdigit() or len(code) != 6:
        await update.message.reply_text("Invalid code. Please enter a 6-digit code.")
        return
    else:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Processing code: {code}...\nPlease wait while I fetch the manga details."
        )
        await asyncio.sleep(2)
        await msg.delete()
        logging.info(f"Received code: {code} from user: {update.effective_user.id}")
        try:
            await cover_page(code, update, context)
        except Exception as e:
            logging.error(f"Error processing code {code}: {e}")
            await update.message.reply_text(f"❌ Error processing code {code}. Please try again later.")
            return
        

#  add/remove new admin
async def add_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in map(str, ADMIN):
        pass
    
    if len(context.args) != 2 or context.args[0] not in ['add', 'remove']:
        await update.message.reply_text("Usage: /admin <add/remove> <user_id>")
        return
    
    action = context.args[0]
    target_user_id = context.args[1]
    
    if action == 'add':
        if target_user_id not in map(str, ADMIN):
            ADMIN.append(target_user_id)
            await update.message.reply_text(f"User {target_user_id} added as admin.")
        else:
            await update.message.reply_text(f"User {target_user_id} is already an admin.")
    
    elif action == 'remove':
        if target_user_id in map(str, ADMIN):
            ADMIN.remove(target_user_id)
            await update.message.reply_text(f"User {target_user_id} removed from admin list.")
        else:
            await update.message.reply_text(f"User {target_user_id} is not an admin.")

# /search command handler
async def search_manga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users(update, context)
    query = ' '.join(context.args)
    formatted_query = query.replace(' ', '+')
    msg_id = update.message.message_id if update.message else None
    
    if not formatted_query:
        await update.message.reply_text("Please provide a search query.")
        return
    else:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Searching for: {query}...\nPlease wait while I fetch the results.",
            reply_to_message_id=msg_id if msg_id else None
        )
        await asyncio.sleep(2)
        await msg.delete()
        
        logging.info(f"Searching for query: {query} from user: {update.effective_user.id}")
        try:
            await search_manga_fuction(update, context, formatted_query, page=1,msg_id=msg_id)
        except Exception as e:
            logging.error(f"Error searching for query {query}: {e}")
            await update.message.reply_text(f"❌ Error searching for query {query}. Please try again later.")
            return
    

# Callback query handler for user interaction
async def query_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split("_")
        action = parts[0]
        
        if action == 'cancel':
            await query.message.delete()
            return
        code = parts[1]
        if action == 'start':
            await query.message.delete()
            download_nhentai_thread(code, update, context)
            return
        await query.edit_message_text("⚠️ Invalid action. Please try again.")
    except Exception as e:
        logging.error(f"Error in query_tap: {e}")
        

# main function to run the bot        
def main():
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

        app = ApplicationBuilder().token(api_id).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("get", get_manga))
        app.add_handler(CommandHandler("search", search_manga))
        app.add_handler(CommandHandler("users", users_data_to_admin))
        app.add_handler(CommandHandler("status", server_status))
        app.add_handler(CallbackQueryHandler(search_query_tap, pattern=r"^next_[^_]+_\d+$"))
        app.add_handler(CallbackQueryHandler(search_query_tap, pattern=r"^prev_[^_]+_\d+$"))
        app.add_handler(CallbackQueryHandler(search_query_tap, pattern=r"^cancel-search_\d+$"))
        app.add_handler(CallbackQueryHandler(search_query_tap, pattern=r"^select-search_\d+$"))
        app.add_handler(CallbackQueryHandler(query_tap, pattern=r"^start_[0-9]+$"))
        app.add_handler(CallbackQueryHandler(query_tap, pattern=r"^cancel_[0-9]+$"))
        app.add_handler(CommandHandler("random", get_random_manga))
        app.add_handler(CommandHandler("admin", add_remove_admin))
        app.add_handler(MessageHandler(filters.COMMAND, lambda update, context: update.message.reply_text("Please send a 6-digit code to download the PDF.")))
        app.run_polling()
        print("Bot is running...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
