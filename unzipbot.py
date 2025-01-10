import os
import zipfile
import rarfile
import gzip
import tarfile
import py7zr
import logging
import asyncio
from logging.handlers import TimedRotatingFileHandler
from config import BOT_TOKEN, API_ID, API_HASH, ALLOWED_USERS
from telegram import Update, error, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
from telethon.sync import TelegramClient

# Path to store temporary files
TEMP_DIR = "temp_files"

# Ensure TEMP_DIR exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Configure logging
when = 'midnight'  # Rotate logs at midnight (other options include 'H', 'D', 'W0' - 'W6', 'MIDNIGHT', or a custom time)
interval = 1  # Rotate daily
backup_count = 7  # Retain logs for 7 days
log_handler = TimedRotatingFileHandler('app.log', when=when, interval=interval, backupCount=backup_count)
log_handler.suffix = "%Y-%m-%d"  # Suffix for log files (e.g., 'my_log.log.2023-10-22')

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        log_handler,
    ]
)

# Create a separate handler for console output with a higher level (WARNING)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # Set the level to WARNING or higher
console_formatter = logging.Formatter("UNZIPBOT: %(message)s")
console_handler.setFormatter(console_formatter)

# Attach the console handler to the root logger
logging.getLogger().addHandler(console_handler)


# Global variables
unzipbot = None
app = None
telethon = None
last_reported_progress = 0
MIN_PROGRESS_UPDATE_SIZE = 3 * 1024 * 1024  # 3 MB
WAITING_FOR_PASSWORD = 1

async def start(update: Update, context: CallbackContext) -> None:
    requester_id = update.message.from_user.id
    if requester_id not in ALLOWED_USERS:
        return
    try:
        await update.message.reply_text("Send me a .zip, .rar, .7z, or .gz file, and I will extract its contents for you!")
    except Exception as e:
        logging.error(f"An error occurred in start: {e}")

async def handle_file(update: Update, context: CallbackContext) -> None:
    """Handle file uploads."""
    # Get the file

    requester_id = update.message.from_user.id
    if requester_id not in ALLOWED_USERS:
        return
    
    global last_reported_progress
    file = update.message.document
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    if not file:
        try:
            await update.message.reply_text("Please send a valid compressed file (.zip, .rar, .7z, .gz).")
        except Exception as e:
            logging.error(f"An error occurred while replying: {e}")
        return

    file_name = file.file_name
    file_size = file.file_size
    if not (file_name.endswith(('.zip', '.rar', '.7z', '.gz'))):
        try:
            await update.message.reply_text("Only .zip, .rar, .7z, or .gz files are supported.")
        except Exception as e:
            logging.error(f"An error occurred while replying: {e}")
        return
    
    try:    
        async def progress_callback(current, total):
            if file_size < MIN_PROGRESS_UPDATE_SIZE:
                return
            global last_reported_progress
            progress = (current / total) * 100
            rounded_progress = int(progress // 10 * 10)  # Round down to the nearest 10%

            if rounded_progress > last_reported_progress:
                last_reported_progress = rounded_progress
                await update.message.reply_text(f"Download progress: {rounded_progress}%")

        original_file_path = os.path.join(TEMP_DIR, file_name)
        await update.message.reply_text("Archive file received. Processing...")
        message = await telethon.get_messages(chat_id, ids=message_id)
        
        try:
            last_reported_progress = 0
            await telethon.download_media(message, file=original_file_path, progress_callback=progress_callback)
        except Exception as e:
            logging.error(f"An error occurred while downloading the file: {e}")
            await update.message.reply_text(f"Failed to download the file: {e}")
            return

        # Extract the contents
        extracted_dir = os.path.join(TEMP_DIR, os.path.splitext(file_name)[0])
        os.makedirs(extracted_dir, exist_ok=True)
        context.user_data["file_name"] = file_name
        context.user_data['original_file_path'] = original_file_path
        context.user_data['extracted_dir'] = extracted_dir
  

        if file_name.endswith('.zip'):
            # Attempt to extract ZIP file
            with zipfile.ZipFile(original_file_path) as archive:
                try:
                    archive.testzip()  # Check if password is required
                except RuntimeError as e:
                    if "password" in e.args[0].lower():
                        context.user_data['password'] = None
                        return await ask_for_password(update, context)
                archive.extractall(extracted_dir)
        elif file_name.endswith('.rar'):
            # Attempt to extract RAR file
            with rarfile.RarFile(original_file_path) as archive:
                if archive.needs_password():
                    context.user_data['password'] = None
                    return await ask_for_password(update, context)
                archive.extractall(extracted_dir)
        elif file_name.endswith('.7z'):
            # Attempt to extract 7Z file
            with py7zr.SevenZipFile(original_file_path, mode='r') as archive:
                try:
                    archive.list()  # Attempt to list the contents
                except py7zr.exceptions.PasswordRequired:
                    context.user_data['password'] = None
                    return await ask_for_password(update, context)
                archive.extractall(extracted_dir)
        elif file_name.endswith('.gz'):
            # Handle GZ files (no password support)
            await extract_gzip(update, context, original_file_path, extracted_dir)
        else:
            await update.message.reply_text("Unsupported file format.")
            return
        await send_extracted_files(update, context, extracted_dir)
    except Exception as e:
        await update.message.reply_text(f"Failed to extract the archive: {e}")
        cleanup(original_file_path, extracted_dir)
        return


    # Send extracted files
async def send_extracted_files(update: Update, context: CallbackContext, extracted_dir: str) -> None:
    retries = 3
    file_number = 0
    original_file_path = context.user_data['original_file_path']
    for root, dirs, files in os.walk(extracted_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            file_number += 1
            file_path = os.path.join(root, file)
            if not os.path.isfile(file_path) or file.startswith('.') or os.path.getsize(file_path) == 0:  
                continue
            if file.lower().endswith(('jpg', 'jpeg', 'png', 'gif')):
                    for attempt in range(retries):
                        try:
                            with open(file_path, 'rb') as photo:
                                await update.message.reply_photo(photo=photo)
                                break
                        except error.TimedOut as e:
                            logging.warning(f"Timed out while sending message, retrying... (attempt {attempt + 1}/{retries})")
                            await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the photo. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 1:
                                await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the photo. Attempting next file...")
                                logging.error(f"Failed to send message after {retries} attempts: {e}")
                                continue
                        except error.NetworkError as e:
                            logging.warning(f"Network error while sending message, retrying... (attempt {attempt + 1}/{retries})")
                            await update.message.reply_text(f"File {file_number}: A network error occurred while sending the photo. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 1:
                                logging.error(f"Failed to send message after {retries} attempts: {e}")
                                await update.message.reply_text(f"File {file_number}: A network error occurred while sending the photo. Attempting next file...")
                                continue
                        except Exception as e:
                            logging.error(f"An error occurred while sending the photo: {e}")
                            await update.message.reply_text(f"File {file_number}: An error occurred while sending the photo. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 1:
                                logging.error(f"Failed to send message after {retries} attempts: {e}")
                                await update.message.reply_text(f"File {file_number}: An error occurred while sending the photo. Attempting next file...")
                                continue
            elif file.lower().endswith(('mp4', 'mov')):
                    for attempt in range(retries):
                        try:
                            with open(file_path, 'rb') as video:
                                await update.message.reply_video(video=video, write_timeout = 180, read_timeout = 180)
                                break
                        except error.TimedOut as e:
                            logging.warning(f"Timed out while sending message, retrying... (attempt {attempt + 1}/{retries})")
                            await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 2:
                                await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting to send as file. (attempt {attempt + 1}/{retries})")
                                logging.error(f"Failed to send message after {retries} attempts: {e} - Attempting to send as file.")
                                try:
                                    await context.bot.send_document(chat_id=update.message.chat_id, document=open(file_path, 'rb'))
                                    break
                                except error.TimedOut as e:
                                    await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting next file...")
                                    logging.error(f"Failed to send message after {retries} attempts: {e}")
                                    continue
                        except error.NetworkError as e:
                            logging.warning(f"Network error while sending message, retrying... (attempt {attempt + 1}/{retries})")
                            await update.message.reply_text(f"File {file_number}: A network error occurred while sending the video. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 2:
                                await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting to send as file. (attempt {attempt + 1}/{retries})")
                                logging.error(f"Failed to send message after {retries} attempts: {e} - Attempting to send as file.")
                                try:
                                    await context.bot.send_document(chat_id=update.message.chat_id, document=open(file_path, 'rb'))
                                    break
                                except error.TimedOut as e:
                                    await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting next file...")
                                    logging.error(f"Failed to send message after {retries} attempts: {e}")
                                    continue
                        except Exception as e:
                            logging.error(f"An error occurred while sending the video: {e}")
                            await update.message.reply_text(f"File {file_number}: An error occurred while sending the video. (attempt {attempt + 1}/{retries})")
                            if attempt == retries - 2:
                                await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting to send as file. (attempt {attempt + 1}/{retries})")
                                logging.error(f"Failed to send message after {retries} attempts: {e} - Attempting to send as file.")
                                try:
                                    await context.bot.send_document(chat_id=update.message.chat_id, document=open(file_path, 'rb'))
                                    break
                                except error.TimedOut as e:
                                    await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the video. Attempting next file...")
                                    logging.error(f"Failed to send message after {retries} attempts: {e}")
                                    continue
            else:
                # Send as a regular file
                for attempt in range(retries):
                    try:
                        with open(file_path, 'rb') as document:
                            await update.message.reply_document(document=document)
                            break
                    except error.TimedOut as e:
                        logging.warning(f"Timed out while sending message, retrying... (attempt {attempt + 1}/{retries})")
                        await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the file. (attempt {attempt + 1}/{retries})")
                        if attempt == retries - 1:
                            await update.message.reply_text(f"File {file_number}: A timeout error occurred while sending the file. Attempting next file...")
                            logging.error(f"Failed to send message after {retries} attempts: {e}")
                            continue
                    except error.NetworkError as e:
                        logging.warning(f"Network error while sending message, retrying... (attempt {attempt + 1}/{retries})")
                        await update.message.reply_text(f"File {file_number}: A network error occurred while sending the file. (attempt {attempt + 1}/{retries})")
                        if attempt == retries - 1:
                            logging.error(f"Failed to send message after {retries} attempts: {e}")
                            await update.message.reply_text(f"File {file_number}: A network error occurred while sending the file. Attempting next file...")
                            continue
                    except Exception as e:
                        logging.error(f"An error occurred while sending the video: {e}")
                        await update.message.reply_text(f"File {file_number}: An error occurred while sending the file. (attempt {attempt + 1}/{retries})")
                        if attempt == retries - 1:
                            logging.error(f"Failed to send message after {retries} attempts: {e}")
                            await update.message.reply_text(f"File {file_number}: An error occurred while sending the file. Attempting next file...")
                            continue
    # Cleanup
    cleanup(original_file_path, extracted_dir)
    await update.message.reply_text("Extraction complete!")


def cleanup(original_file_path, extracted_dir):
    if os.path.exists(original_file_path):
        try:
            os.remove(original_file_path)
        except Exception as e:
            pass

    for root, dirs, files in os.walk(extracted_dir, topdown=False):
        for name in files:
            file_path = os.path.join(root, name)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    pass

        for name in dirs:
            dir_path = os.path.join(root, name)
            if os.path.exists(dir_path):
                try:
                    os.rmdir(dir_path)
                except Exception as e:
                    pass

    if os.path.exists(extracted_dir):
        try:
            os.rmdir(extracted_dir)
        except Exception as e:
            pass


async def extract_gzip(update: Update, context: CallbackContext, file_path: str, output_dir: str) -> None:
    """Extract .gz files."""
    base_name = os.path.basename(file_path)
    output_file = os.path.join(output_dir, os.path.splitext(base_name)[0])  # Remove .gz extension
    with gzip.open(file_path, 'rb') as gz_file, open(output_file, 'wb') as out_file:
        out_file.write(gz_file.read())

    # If the decompressed file is a tarball, extract it
    if tarfile.is_tarfile(output_file):
        with tarfile.open(output_file, 'r') as tar:
            try:
                tar.extractall(output_dir)
            except tarfile.ReadError as e:
                if "password" in str(e).lower():
                    await update.message.reply_text("This tarball is password-protected. Please provide the password:")
                    context.user_data['password'] = None
                    context.user_data['output_file'] = output_file
                    context.user_data['output_dir'] = output_dir
                    return await ask_for_password(update, context)

        await send_extracted_files(update, context, output_dir)
        os.remove(output_file)  # Clean up the tarball


async def ask_for_password(update: Update, context: CallbackContext) -> int:
    """Prompt the user for a password."""
    await update.message.reply_text("This archive is password-protected. Please provide the password:")
    return WAITING_FOR_PASSWORD


async def receive_password(update: Update, context: CallbackContext) -> int:
    """Receive the password from the user."""
    retries = 3
    password = update.message.text
    context.user_data['password'] = password
    file_name = context.user_data['file_name']

    original_file_path = context.user_data['original_file_path']
    extracted_dir = context.user_data['extracted_dir']
    for attempt in range(retries):
        try:
            if file_name.endswith('.zip'):
                with zipfile.ZipFile(original_file_path) as archive:
                    archive.setpassword(password.encode())
                    archive.extractall(extracted_dir)
            elif file_name.endswith('.rar'):
                with rarfile.RarFile(original_file_path) as archive:
                    archive.extractall(extracted_dir, pwd=password.encode())
            elif file_name.endswith('.7z'):
                with py7zr.SevenZipFile(original_file_path, mode='r') as archive:
                    archive.extractall(extracted_dir, password=password)
            elif file_name.endswith('.gz'):
                output_file = context.user_data['output_file']
                output_dir = context.user_data['output_dir']
                with tarfile.open(output_file, 'r:gz', pwd=password.encode()) as tar:
                    tar.extractall(output_dir)
            await update.message.reply_text("Archive extracted successfully. Sending files...")
            await send_extracted_files(update, context, extracted_dir)
            return ConversationHandler.END
        except RuntimeError as e:
            if "Bad password" in str(e):
                await update.message.reply_text("Incorrect password. Please try again.")
                if attempt == retries - 1:
                    await update.message.reply_text("Too many incorrect attempts. Operation cancelled.")
                    return ConversationHandler.END
                return WAITING_FOR_PASSWORD
            else:
                await update.message.reply_text(f"Failed to extract archive: {e}")
                return ConversationHandler.END   
        finally:
            cleanup(original_file_path, extracted_dir) 
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def handle_file_loop(update: Update, context: CallbackContext) -> None:
    return asyncio.create_task(handle_file(update, context))



def main():
    """Main function to start the bot."""

    global unzipbot
    global app
    global telethon

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    # app.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.ATTACHMENT, handle_file_loop)],
        states={
            WAITING_FOR_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)

    try:
        if not API_ID and API_HASH:
            logging.info("Please fill in the API_ID and API_HASH in the config.py file.")
            return
        telethon = TelegramClient('memberlist_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
        unzipbot = app.bot
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(e)

if __name__ == "__main__":
    main()
