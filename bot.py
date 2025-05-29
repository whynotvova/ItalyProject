import asyncio
import sys
import os
import re
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InputMediaPhoto, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
from config import BOT_TOKENS, BOT_CONFIGS
from database import Database
from utils import adjust_price, add_watermark, download_photo, extract_sizes, select_unique_photos
import mysql.connector

# Define which bot to run
BOT_NAME = os.getenv("BOT_NAME", "bella")
if BOT_NAME not in BOT_TOKENS:
    raise ValueError(f"Invalid bot name: {BOT_NAME}. Must be one of {list(BOT_TOKENS.keys())}")

bot = Bot(token=BOT_TOKENS[BOT_NAME])
dp = Dispatcher()
db = Database()
config = BOT_CONFIGS[BOT_NAME]
router = Router()
dp.include_router(router)

# List of project bot IDs
PROJECT_BOT_IDS = [
    7432922492,  # Lucia
    8151632568,  # Luna
    7577560442,  # Leo
    7973851098  # Bella
]

# Temporary storage for media group photos
media_groups = {}

def is_valid_file_id(file_id):
    """Validate Telegram file_id (alphanumeric, >20 chars)."""
    return bool(file_id and isinstance(file_id, str) and len(file_id) > 20 and re.match(r'^[A-Za-z0-9_-]+$', file_id))


async def send_with_retry(func, *args, max_retries=3, **kwargs):
    """Execute a send function with retry logic for rate limits."""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except TelegramBadRequest as e:
            if "Too Many Requests" in str(e):
                delay = 2 ** (attempt + 1)  # Exponential backoff: 2, 4, 8 seconds
                print(f"Debug - Rate limit hit, retrying in {delay}s, attempt {attempt + 1}/{max_retries}")
                await asyncio.sleep(delay)
            else:
                raise
    raise TelegramBadRequest("Max retries reached due to rate limits")


async def queue_post(user_id, photo_ids, description, message_id):
    """Queue a post for processing if not a duplicate."""
    photo_ids_str = ','.join(photo_ids)
    if db.check_queue_duplicate(user_id, photo_ids_str, description):
        print(
            f"Debug - Duplicate post detected: user_id={user_id}, photo_ids={photo_ids_str}, description={description}")
        await bot.send_message(user_id, "Этот пост уже в очереди.")
        return False
    try:
        db.queue_post(user_id, photo_ids_str, description, message_id)
        print(
            f"Debug - Queued post: user_id={user_id}, message_id={message_id}, photo_ids={photo_ids_str}, description={description}")
        return True
    except mysql.connector.Error as e:
        print(f"Debug - Error logging post: {e}")
        await bot.send_message(user_id, f"Ошибка при добавлении поста в очередь: {str(e)}")
        return False


async def process_queue():
    """Background task to process queued posts sequentially."""
    while True:
        post = db.get_next_queued_post()
        if not post:
            await asyncio.sleep(1)
            continue
        post_id, user_id, photo_ids_str, description, message_id = post
        photo_ids = [pid for pid in photo_ids_str.split(',') if is_valid_file_id(pid)]
        print(
            f"Debug - Processing queued post: post_id={post_id}, user_id={user_id}, photo_ids={photo_ids}, description={description}")
        if not photo_ids:
            print(f"Debug - No valid photo IDs for post_id={post_id}, marking as failed")
            db.update_queue_status(post_id, 'failed')
            await bot.send_message(user_id, f"Ошибка: недействительные идентификаторы фото для поста {post_id}.")
            await asyncio.sleep(3)
            continue
        try:
            db.update_queue_status(post_id, 'processing')
            class MockMessage:
                def __init__(self, user_id, message_id, photo_ids, caption):
                    self.message_id = message_id
                    self.from_user = type('User', (), {'id': user_id})()
                    self.chat = type('Chat', (), {'id': user_id})()
                    self.photo = [MockPhoto(file_id=pid) for pid in photo_ids]
                    self.caption = caption
                    self.forward_from = None
                    self.forward_from_chat = None
                    self.forward_from_message_id = None
                async def reply(self, text, **kwargs):
                    return await bot.send_message(chat_id=self.from_user.id, text=text, **kwargs)
            class MockPhoto:
                def __init__(self, file_id):
                    self.file_id = file_id
                    self.file_size = 1  # Dummy value
            mock_message = MockMessage(user_id, message_id, photo_ids, description)
            await handle_photo_post(mock_message)
            db.update_queue_status(post_id, 'sent')
            print(f"Debug - Successfully processed queued post: post_id={post_id}")
            await asyncio.sleep(3)  # Delay to avoid rate limits
        except Exception as e:
            print(f"Debug - Error processing queued post {post_id}: {e}")
            db.update_queue_status(post_id, 'failed')
            await bot.send_message(chat_id=user_id, text=f"Ошибка при обработке поста: {str(e)}")
            await asyncio.sleep(3)


# Handler for photo messages
@router.message(F.photo)
async def handle_photo(message: Message):
    print(
        f"Debug - Received photo: message_id={message.message_id}, caption={message.caption or ''}, photo_count={len(message.photo)}, media_group_id={message.media_group_id or 'None'}")
    print(f"Debug - Photo details: {[(p.file_id, p.file_size) for p in message.photo]}")
    # Check if message is forwarded
    is_forwarded = message.forward_from is not None or message.forward_from_chat is not None or message.forward_from_message_id is not None
    # Select highest-resolution photo per message
    valid_photos = [max(message.photo, key=lambda p: p.file_size) for photo in message.photo if
                    is_valid_file_id(photo.file_id)]
    if not valid_photos:
        print(f"Debug - No valid photo IDs in message: message_id={message.message_id}")
        await message.reply("Ошибка: отправленные фото имеют недействительные идентификаторы.")
        return
    if message.media_group_id:
        # Media group: collect unique high-resolution photos
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = {
                'user_id': message.from_user.id,
                'message_id': message.message_id,
                'photo_ids': [],
                'timeout_task': None
            }
        # Add only the highest-resolution photo ID, avoiding duplicates
        new_photo_id = valid_photos[0].file_id
        if new_photo_id not in media_groups[message.media_group_id]['photo_ids']:
            media_groups[message.media_group_id]['photo_ids'].append(new_photo_id)
        print(
            f"Debug - Added to media group: media_group_id={message.media_group_id}, photo_ids={media_groups[message.media_group_id]['photo_ids']}")
        # Cancel previous timeout task if exists
        if media_groups[message.media_group_id]['timeout_task']:
            media_groups[message.media_group_id]['timeout_task'].cancel()
        # Schedule task to log media group after delay
        async def log_media_group(mg_id):
            await asyncio.sleep(1)  # Wait for all media group messages
            mg_data = media_groups.get(mg_id)
            if mg_data:
                valid_photo_ids = [pid for pid in mg_data['photo_ids'] if is_valid_file_id(pid)]
                if not valid_photo_ids:
                    print(f"Debug - No valid photo IDs in media group: media_group_id={mg_id}")
                    await bot.send_message(mg_data['user_id'],
                                           "Ошибка: все фото в медиагруппе имеют недействительные идентификаторы.")
                    del media_groups[mg_id]
                    return
                photo_ids_str = ','.join(valid_photo_ids)
                print(
                    f"Debug - Storing media group photos: user_id={mg_data['user_id']}, message_id={mg_data['message_id']}, photo_ids={photo_ids_str}, media_group_id={mg_id}")
                try:
                    db.log_pending_photo(
                        user_id=mg_data['user_id'],
                        message_id=mg_data['message_id'],
                        photo_ids=valid_photo_ids,
                        media_group_id=mg_id
                    )
                    await bot.send_message(mg_data['user_id'], "Фото получено. Пожалуйста, отправьте описание товара.")
                    print(f"Debug - Logged media group photos: media_group_id={mg_id}")
                except mysql.connector.Error as e:
                    print(f"Debug - Database error logging media group photo: {e}")
                    await bot.send_message(mg_data['user_id'], f"Ошибка при сохранении фото: {str(e)}")
                del media_groups[mg_id]
        media_groups[message.media_group_id]['timeout_task'] = asyncio.create_task(
            log_media_group(message.media_group_id))
        photo_ids = media_groups[message.media_group_id]['photo_ids']
    else:
        # Single photo: select highest-resolution photo
        photo_ids = [valid_photos[0].file_id]
        print(f"Debug - Selected photo IDs: {photo_ids}, photo_count={len(photo_ids)}")
    if is_forwarded or message.caption:
        # Method 1: Photo(s) with caption or forwarded
        if await queue_post(message.from_user.id, photo_ids, message.caption or "", message.message_id):
            await message.reply("Пост добавлен в очередь для обработки.")
        return

    # Method 2: Store single photo for separate text
    if not message.media_group_id:
        photo_ids_str = ','.join(photo_ids)
        print(
            f"Debug - Storing single photo: user_id={message.from_user.id}, message_id={message.message_id}, photo_ids={photo_ids_str}, media_group_id=None")
        try:
            db.log_pending_photo(
                user_id=message.from_user.id,
                message_id=message.message_id,
                photo_ids=photo_ids,
                media_group_id=None
            )
            await message.reply("Фото получено. Пожалуйста, отправьте описание товара.")
            print(f"Debug - Logged single photo: message_id={message.message_id}")
        except mysql.connector.Error as e:
            print(f"Debug - Database error logging single photo: {e}")
            await message.reply(f"Ошибка при сохранении фото: {str(e)}")


# Handler for text messages
@router.message(F.text)
async def handle_text(message: Message):
    print(f"Debug - Received text: message_id={message.message_id}, text={message.text}")
    pending_photos = db.get_pending_photos(message.from_user.id)
    if not pending_photos:
        print(f"Debug - No pending photos found for user_id={message.from_user.id}")
        await message.reply("Сначала отправьте фото товара.")
        return

    # Select the latest pending photo set
    latest_pending = max(pending_photos, key=lambda x: x[0])  # Latest by message_id
    pending_message_id, photo_ids_str, media_group_id = latest_pending
    photo_ids = [pid for pid in photo_ids_str.split(',') if is_valid_file_id(pid)]
    if not photo_ids:
        print(
            f"Debug - No valid photo IDs in pending photos: message_id={pending_message_id}, user_id={message.from_user.id}")
        await message.reply("Ошибка: сохраненные фото имеют недействительные идентификаторы.")
        db.clear_pending_photos(message.from_user.id)
        return

    # If media group, fetch unique photos
    if media_group_id:
        media_group_photos = db.get_pending_photos(message.from_user.id, media_group_id=media_group_id)
        if media_group_photos:
            photo_ids = list(set([pid for pid in media_group_photos[0][1].split(',') if is_valid_file_id(pid)]))
            print(
                f"Debug - Selected media group photos: message_id={pending_message_id}, photo_ids={photo_ids}, media_group_id={media_group_id}")
        else:
            print(f"Debug - No photos found for media_group_id={media_group_id}")
            await message.reply("Ошибка: фото медиагруппы не найдены.")
            return
    else:
        print(
            f"Debug - Selected single photo: message_id={pending_message_id}, photo_ids={photo_ids}, media_group_id=None")

    # Queue the pair and clear pending photos only on success
    if await queue_post(message.from_user.id, photo_ids, message.text, message.message_id):
        await message.reply("Пост добавлен в очередь для обработки.")
        db.clear_pending_photos(message.from_user.id)
        print(f"Debug - Cleared pending photos for user_id={message.from_user.id}")
    else:
        await message.reply("Пост уже в очереди или произошла ошибка.")


# Handler for photo posts
async def handle_photo_post(message: Message):
    print(
        f"Debug - Processing photo post: message_id={message.message_id}, caption={message.caption or ''}, photo_count={len(message.photo)}")
    description = message.caption or ""
    print(f"Debug - Description: {description}")

    # Use unique high-resolution photos
    photo_ids = select_unique_photos(message.photo)
    print(f"Debug - Processing photo IDs: {photo_ids}, count={len(photo_ids)}")
    if not photo_ids:
        print(f"Debug - No valid photo IDs in handle_photo_post: message_id={message.message_id}")
        await message.reply("Ошибка: недействительные идентификаторы фото.")
        return
    brand_match = re.search(r'^([A-Za-z\s&]+?)(?=\s*\d+\.?\d*\$|$)', description, re.IGNORECASE)
    brand = brand_match.group(1).strip() if brand_match else "Unknown"
    price_match = re.search(r'(\d+\.?\d*)\$', description)
    price = float(price_match.group(1)) if price_match else None
    sizes = extract_sizes(description)
    print(f"Debug - Extracted: brand={brand}, price={price}, sizes={sizes}")
    is_forwarded = message.forward_from is not None or message.forward_from_chat is not None or message.forward_from_message_id is not None
    corrected_brand, target_groups, target_topic = db.get_corrected_brand(brand.lower())
    if corrected_brand == "Unknown":
        corrected_brand = brand
    print(f"Debug - Corrected brand: {corrected_brand}")
    if is_forwarded:
        db.clear_stale_forwarded_posts(message.from_user.id)
        post = None
        forwarded_from_message_id = message.forward_from_message_id
        if forwarded_from_message_id:
            post = db.get_post_by_forward_from_message_id(forwarded_from_message_id)
        if not post and price:
            post = db.get_post_by_caption(corrected_brand, price)
        if not post and photo_ids:
            post = db.get_post_by_photo_id(photo_ids[0], corrected_brand)
        if not post:
            await message.reply("Исходный пост не найден.")
            print(f"Debug - No post found for forwarded post")
            return
        brand, current_price, original_price, photo_ids_db, client_message_id, client_chat_id, client_topic_name, sizes_db = post
        print(f"Debug - Found post: client_message_id={client_message_id}")
        if not client_message_id or not client_chat_id:
            await message.reply("Пост не имеет данных для обновления.")
            return
        if not original_price:
            await message.reply("Оригинальная цена отсутствует.")
            return
        adjusted_price, percentage = adjust_price(description) if config["adjust_price"] else (original_price, None)
        if not adjusted_price:
            await message.reply("Не удалось определить цену.")
            return
        new_description = f"{brand} {adjusted_price}$ {percentage or ''} {sizes or sizes_db or ''}".strip()
        try:
            await bot.delete_message(chat_id=client_chat_id, message_id=client_message_id)
            await asyncio.sleep(3)
            if len(photo_ids) > 1:
                media_group = [
                    InputMediaPhoto(media=pid, caption=new_description if i == 0 else None)
                    for i, pid in enumerate(photo_ids)
                ]
                sent_messages = await send_with_retry(
                    bot.send_media_group,
                    chat_id=client_chat_id,
                    media=media_group,
                    message_thread_id=db.get_topic_thread_id(client_chat_id, client_topic_name)
                )
                new_client_message_id = sent_messages[0].message_id
            else:
                sent_message = await send_with_retry(
                    bot.send_photo,
                    chat_id=client_chat_id,
                    photo=photo_ids[0],
                    caption=new_description,
                    message_thread_id=db.get_topic_thread_id(client_chat_id, client_topic_name)
                )
                new_client_message_id = sent_message.message_id
            db.update_post_price(new_client_message_id, adjusted_price, percentage)
            print(f"Debug - Replaced client post {client_message_id} with new message_id={new_client_message_id}")
            await asyncio.sleep(3)
            post = db.get_post_by_client_message_id(client_message_id)
            if post:
                _, _, _, _, _, _, _, _, buyer_message_ids_str = post
                if buyer_message_ids_str:
                    buyer_message_ids = buyer_message_ids_str.split(',')
                    buyer_price_match = re.search(r'(\d+\.?\d*)\$', description)
                    buyer_price = float(buyer_price_match.group(1)) if buyer_price_match else original_price
                    buyer_percentage_match = re.search(r'([-+]\d+)%', description)
                    buyer_percentage = buyer_percentage_match.group(1) if buyer_percentage_match else None
                    buyer_caption = f"{brand} {buyer_price}$ {buyer_percentage or ''} {sizes or sizes_db or ''}".strip()
                    for idx, buyer_group in enumerate(config["forward_to_buyers"]):
                        if idx < len(buyer_message_ids):
                            buyer_message_id = buyer_message_ids[idx]
                            buyer_chat_id = db.get_group_info(buyer_group)
                            if buyer_chat_id:
                                try:
                                    await bot.delete_message(chat_id=buyer_chat_id, message_id=int(buyer_message_id))
                                    await asyncio.sleep(3)
                                    if len(photo_ids) > 1:
                                        media_group = [
                                            InputMediaPhoto(media=pid, caption=buyer_caption if i == 0 else None)
                                            for i, pid in enumerate(photo_ids)
                                        ]
                                        sent_buyer_messages = await send_with_retry(
                                            bot.send_media_group,
                                            chat_id=buyer_chat_id,
                                            media=media_group
                                        )
                                        new_buyer_message_id = sent_buyer_messages[0].message_id
                                    else:
                                        sent_buyer_message = await send_with_retry(
                                            bot.send_photo,
                                            chat_id=buyer_chat_id,
                                            photo=photo_ids[0],
                                            caption=buyer_caption
                                        )
                                        new_buyer_message_id = sent_buyer_message.message_id
                                    buyer_message_ids[idx] = str(new_buyer_message_id)
                                    print(f"Debug - Replaced buyer post in {buyer_group}")
                                    await asyncio.sleep(3)
                                except TelegramBadRequest as e:
                                    print(f"Debug - Error updating buyer post: {e}")
                    buyer_message_ids_str = ','.join(buyer_message_ids)
                    db.cursor.execute(
                        "UPDATE posts SET buyer_message_ids = %s, client_message_id = %s WHERE client_message_id = %s",
                        (buyer_message_ids_str, new_client_message_id, client_message_id)
                    )
                    db.conn.commit()
            db.log_forwarded_post(
                user_id=message.from_user.id,
                bot_name=BOT_NAME,
                message_id=message.message_id,
                brand=corrected_brand,
                photo_ids=photo_ids,
                caption=description,
                forward_from_message_id=forwarded_from_message_id,
                client_message_id=new_client_message_id
            )
            db.delete_forwarded_post(message.message_id)
            await message.reply(f"Пост обновлен: {new_description}")
        except TelegramBadRequest as e:
            print(f"Debug - Telegram error updating post: {e}")
            await message.reply(f"Ошибка при обновлении поста: {e}")
            db.delete_forwarded_post(message.message_id)
        return
    if config["sort_by_brand"]:
        if corrected_brand == "Unknown":
            await message.reply("Не удалось определить бренд.")
            return
        if not target_groups or not target_topic:
            await message.reply(f"Целевая группа или топик не найдены для бренда: {corrected_brand}.")
            return
        target_group = target_groups[0]
    else:
        target_group = config["target_group"]
        target_topic = config["target_topic"]
        if not target_group or not target_topic:
            await message.reply(f"Конфигурация группы или топика отсутствует.")
            return
    existing_posts = db.get_existing_posts(corrected_brand, photo_ids, price)
    if existing_posts:
        for client_message_id, client_chat_id, client_topic_name, _, existing_sizes in existing_posts:
            adjusted_price, percentage = adjust_price(description) if config["adjust_price"] and price else (
                price, None)
            client_caption = f"{corrected_brand} {adjusted_price}$ {percentage or ''}"
            try:
                await bot.edit_message_caption(
                    chat_id=client_chat_id,
                    message_id=client_message_id,
                    caption=client_caption
                )
                db.update_post_price(client_message_id, adjusted_price or price, percentage)
                buyer_price_match = re.search(r'(\d+\.?\d*)\$', description)
                buyer_price = float(buyer_price_match.group(1)) if buyer_price_match else price
                buyer_percentage_match = re.search(r'([-+]\d+)%', description)
                buyer_percentage = buyer_percentage_match.group(1) if buyer_percentage_match else None
                await forward_to_buyers(
                    message,
                    photo_ids,
                    corrected_brand,
                    buyer_price,
                    sizes,
                    config["forward_to_buyers"],
                    client_message_id,
                    f"{corrected_brand} {buyer_price}$ {buyer_percentage or ''} {sizes or ''}"
                  )
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    await message.reply("Описание поста не изменилось.")
                else:
                    await message.reply(f"Ошибка при обновлении поста: {str(e)}")
                return
    watermarked_photos = photo_ids.copy()
    watermarked_photo_ids = [None] * len(photo_ids)
    if config["add_watermark"]:
        watermarked_photos = []
        for i, photo_id in enumerate(photo_ids):
            try:
                photo_data = await download_photo(photo_id, bot)
                watermarked_data = await add_watermark(photo_data, target_group)
                watermarked_file = BufferedInputFile(watermarked_data, filename=f"photo_{i}.jpg")
                watermarked_photos.append(watermarked_file)
            except Exception as e:
                print(f"Debug - Error watermarking photo {photo_id}: {e}")
                watermarked_photos.append(photo_id)
    chat_id = db.get_group_info(target_group)
    if not chat_id:
        await message.reply(f"Группа {target_group} не найдена.")
        return
    message_thread_id = db.get_topic_thread_id(target_group, target_topic)
    print(
        f"Debug - Sending to client group: {target_group}, chat_id={chat_id}, topic={target_topic}, message_thread_id={message_thread_id}, photo_count={len(photo_ids)}")
    adjusted_price, percentage = adjust_price(description) if config["adjust_price"] and price else (price, None)
    client_caption = f"{corrected_brand} {adjusted_price}$ {percentage or ''} {sizes or ''}"
    try:
        await asyncio.sleep(3)
        if len(watermarked_photos) > 1:
            media_group = [
                InputMediaPhoto(media=watermarked_photos[i], caption=client_caption if i == 0 else None)
                for i in range(len(watermarked_photos))
            ]
            sent_messages = await send_with_retry(
                bot.send_media_group,
                chat_id=chat_id,
                media=media_group,
                message_thread_id=message_thread_id
            )
            sent_message = sent_messages[0]
        else:
            sent_message = await send_with_retry(
                bot.send_photo,
                chat_id=chat_id,
                photo=watermarked_photos[0],
                caption=client_caption,
                message_thread_id=message_thread_id
            )
        print(f"Debug - Successfully sent to client group {target_group}: message_id={sent_message.message_id}")
        await asyncio.sleep(3)
        if sent_message:
            if config["add_watermark"]:
                if len(watermarked_photos) > 1:
                    watermarked_photo_ids = [msg.photo[-1].file_id for msg in sent_messages if msg.photo]
                else:
                    watermarked_photo_ids = [sent_message.photo[-1].file_id] if sent_message.photo else [None]
            buyer_price_match = re.search(r'(\d+\.?\d*)\$', description)
            buyer_price = float(buyer_price_match.group(1)) if buyer_price_match else price
            buyer_percentage_match = re.search(r'([-+]\d+)%', description)
            buyer_percentage = buyer_percentage_match.group(1) if buyer_percentage_match else None
            await forward_to_buyers(
                message,
                photo_ids,
                corrected_brand,
                buyer_price,
                sizes,
                config["forward_to_buyers"],
                sent_message.message_id,
                f"{corrected_brand} {buyer_price}$ {buyer_percentage or ''} {sizes or ''}"
            )
            db.log_post(
                bot_name=BOT_NAME,
                message_id=message.message_id,
                brand=corrected_brand,
                price=adjusted_price or price,
                adjusted_price=percentage,
                sizes=sizes,
                photo_ids=','.join(photo_ids),
                client_message_id=sent_message.message_id,
                client_chat_id=chat_id,
                client_topic_name=target_topic,
                forward_from_message_id=message.forward_from_message_id,
                watermarked_photo_ids=','.join([pid for pid in watermarked_photo_ids if pid])
            )
    except Exception as e:
        await message.reply(f"Ошибка при отправке в группу {target_group}: {e}")
        print(f"Debug - Error sending to client group {target_group}: {e}")
        raise  # Re-raise to mark post as failed in process_queue


async def forward_to_buyers(message, photo_ids, corrected_brand, price, sizes, buyer_groups, client_message_id,
                            full_caption=None):
    buyer_message_ids = []
    for buyer_group in buyer_groups:
        buyer_chat_id = db.get_group_info(buyer_group)
        if not buyer_chat_id:
            print(f"Debug - Buyer group {buyer_group} not found")
            continue
        # Define buyer_caption using full_caption or construct from parameters
        buyer_caption = full_caption.strip() if full_caption else f"{corrected_brand} {price}$ {sizes or ''}"
        print(f"Debug - Sending to buyer group: {buyer_group}, chat_id={buyer_chat_id}, photo_count={len(photo_ids)}")
        try:
            await asyncio.sleep(3)
            if len(photo_ids) > 1:
                media_group = [
                    InputMediaPhoto(media=pid, caption=buyer_caption if i == 0 else None)
                    for i, pid in enumerate(photo_ids)
                ]
                sent_messages = await send_with_retry(
                    bot.send_media_group,
                    chat_id=buyer_chat_id,
                    media=media_group
                )
                buyer_message_id = sent_messages[0].message_id
            else:
                sent_message = await send_with_retry(
                    bot.send_photo,
                    chat_id=buyer_chat_id,
                    photo=photo_ids[0],
                    caption=buyer_caption
                )
                buyer_message_id = sent_message.message_id
            buyer_message_ids.append(buyer_message_id)
            print(f"Debug - Successfully sent to buyer group {buyer_group}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Debug - Error sending to buyer group {buyer_group}: {e}")

    if buyer_message_ids:
        try:
            buyer_message_ids_str = ','.join(map(str, buyer_message_ids))
            db.cursor.execute(
                "UPDATE posts SET buyer_message_ids = %s WHERE client_message_id = %s",
                (buyer_message_ids_str, client_message_id)
            )
            db.conn.commit()
            print(f"Debug - Updated buyer_message_ids for client_message_id={client_message_id}")
        except mysql.connector.Error as e:
            print(f"Debug - Error updating buyer_message_ids: {e}")


# Setup and run bot
async def main():
    print(f"Bot {BOT_NAME} started!")
    # Start queue processing task
    asyncio.create_task(process_queue())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print(f"Bot {BOT_NAME} stopped!")
        db.close()