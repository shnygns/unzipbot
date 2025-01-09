import os
import zipfile
import rarfile
import gzip
import tarfile
import py7zr
import logging
from logging.handlers import TimedRotatingFileHandler
from config import BOT_TOKEN, API_ID, API_HASH, ALLOWED_USERS
from telegram import Update, InputFile, error
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telethon.sync import TelegramClient
from telethon.errors import ChannelPrivateError, BadRequestError, UserAdminInvalidError, TimedOutError, UserDeletedError, UsernameInvalidError

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

        password_attempts = 3
        for attempt in range(password_attempts):
            try:
                if file_name.endswith('.zip'):
                    # Attempt to extract ZIP file
                    with zipfile.ZipFile(original_file_path) as archive:
                        if archive.testzip():  # Check if password is required
                            await update.message.reply_text("This archive is password-protected. Please provide the password:")
                            password = await get_user_response(update, context)
                            archive.setpassword(password.encode())
                        archive.extractall(extracted_dir)
                elif file_name.endswith('.rar'):
                    # Attempt to extract RAR file
                    with rarfile.RarFile(original_file_path) as archive:
                        if archive.needs_password():
                            await update.message.reply_text("This archive is password-protected. Please provide the password:")
                            password = await get_user_response(update, context)
                            archive.extractall(extracted_dir, pwd=password)
                elif file_name.endswith('.7z'):
                    # Attempt to extract 7Z file
                    with py7zr.SevenZipFile(original_file_path, mode='r') as archive:
                        await update.message.reply_text("This archive is password-protected. Please provide the password:")
                        password = await get_user_response(update, context)
                        archive.extractall(extracted_dir, password=password)
                elif file_name.endswith('.gz'):
                    # Handle GZ files (no password support)
                    extract_gzip(original_file_path, extracted_dir)
                else:
                    await update.message.reply_text("Unsupported file format.")
                    return
                break  # Break the loop if extraction succeeds
            except (zipfile.BadZipFile, rarfile.BadRarFile, py7zr.Bad7zFile, RuntimeError) as e:
                logging.error(f"Password attempt {attempt + 1} failed: {e}")
                if attempt < password_attempts - 1:
                    await update.message.reply_text("Incorrect password. Please try again.")
                else:
                    await update.message.reply_text("Too many incorrect attempts. Extraction aborted.")
                    cleanup(original_file_path, extracted_dir)
                    return
    except Exception as e:
        await update.message.reply_text(f"Failed to extract the archive: {e}")
        cleanup(original_file_path, extracted_dir)
        return

        """
        if file_name.endswith('.zip'):
            with zipfile.ZipFile(original_file_path, 'r') as archive:
                archive.extractall(extracted_dir)
        elif file_name.endswith('.rar'):
            with rarfile.RarFile(original_file_path, 'r') as archive:
                archive.extractall(extracted_dir)
        elif file_name.endswith('.7z'):
            with py7zr.SevenZipFile(original_file_path, mode='r') as archive:
                archive.extractall(extracted_dir)
        elif file_name.endswith('.gz'):
            extract_gzip(original_file_path, extracted_dir)
        else:
            update.message.reply_text("Unsupported file format.")
            return
    except Exception as e:
        await update.message.reply_text(f"Failed to extract the archive: {e}")
        cleanup(original_file_path, extracted_dir)
        return
    """
    # Send extracted files
    for root, dirs, files in os.walk(extracted_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            file_path = os.path.join(root, file)
            if not os.path.isfile(file_path) or file.startswith('.') or os.path.getsize(file_path) == 0:  
                continue
            if file.lower().endswith(('jpg', 'jpeg', 'png', 'gif')):
                    try:
                        with open(file_path, 'rb') as photo:
                            await send_with_retry(update.message.reply_photo, photo=open(file_path, 'rb'))
                    except Exception as e:
                        logging.error(f"An error occurred while sending the photo: {e}")
                        await update.message.reply_text("An error occurred while sending the photo.")
            elif file.lower().endswith(('mp4', 'mov')):
                    try:
                        with open(file_path, 'rb') as video:
                            await send_with_retry(update.message.reply_video, video=video)
                    except Exception as e:
                        logging.error(f"An error occurred while sending the video: {e}")
                        await update.message.reply_text("An error occurred while sending the video.")
            else:
                # Send as a regular file
                try:
                    with open(file_path, 'rb') as document:
                        await send_with_retry(update.message.reply_document, document=document)
                except Exception as e:
                    logging.error(f"An error occurred while sending the document: {e}")
                    await update.message.reply_text("An error occurred while sending the document.")

    # Cleanup
    cleanup(original_file_path, extracted_dir)
    await update.message.reply_text("Extraction complete!")


def cleanup(original_file_path, extracted_dir):
    os.remove(original_file_path)
    for root, dirs, files in os.walk(extracted_dir, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    os.rmdir(extracted_dir)


async def send_with_retry(send_func, **kwargs):
    """Send a message with retry mechanism."""
    retries = 3
    for attempt in range(retries):
        try:
            await send_func(**kwargs)  # Increase timeout to 60 seconds
            break
        except error.TimedOut as e:
            logging.warning(f"Timed out while sending message, retrying... (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                logging.error(f"Failed to send message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"An error occurred while sending message: {e}")
            raise


def extract_gzip(file_path, output_dir):
    """Extract .gz files."""
    base_name = os.path.basename(file_path)
    output_file = os.path.join(output_dir, os.path.splitext(base_name)[0])  # Remove .gz extension
    with gzip.open(file_path, 'rb') as gz_file, open(output_file, 'wb') as out_file:
        out_file.write(gz_file.read())

    # If the decompressed file is a tarball, extract it
    if tarfile.is_tarfile(output_file):
        with tarfile.open(output_file, 'r') as tar:
            tar.extractall(output_dir)
        os.remove(output_file)  # Clean up the tarball


async def get_user_response(update: Update, context: CallbackContext) -> str:
    """Wait for the user to send a password."""
    def check_response(reply_update):
        return reply_update.message.chat_id == update.message.chat_id

    response = await context.bot.wait_for("message", check=check_response, timeout=60)
    return response.text


def main():
    """Main function to start the bot."""

    global unzipbot
    global app
    global telethon

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))

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
