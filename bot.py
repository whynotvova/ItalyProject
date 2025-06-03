import asyncio
import sys
import os
import re
import uuid
import time
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InputMediaPhoto, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
from config import BOT_TOKENS, BOT_CONFIGS, PROJECT_BOT_IDS
from database import Database
from utils import adjust_price, add_watermark, download_photo, extract_sizes, select_unique_photos
import mysql.connector

BOT_NAME = os.getenv("BOT_NAME", "bella")
if BOT_NAME not in BOT_TOKENS:
    raise ValueError(f"Invalid bot name: {BOT_NAME}. Must be one of {list(BOT_TOKENS.keys())}")

bot = Bot(token=BOT_TOKENS[BOT_NAME])
dp = Dispatcher()
db = Database()
config = BOT_CONFIGS[BOT_NAME]
router = Router()
dp.include_router(router)

media_groups = {}
queue_lock = asyncio.Lock()

def update_caption_price_and_percentage(caption, new_price, new_percentage, currency, brand=None):
    if not caption:
        return f"{brand or 'Unknown'} {new_price}{currency} {new_percentage}" if new_percentage else f"{brand or 'Unknown'} {new_price}{currency}"

    price_pattern = r'(\d+\.?\d*)\s*([€$])'
    percentage_pattern = r'([-+]\d+%?)'

    brand_match = re.search(r'^\s*([A-Za-z\s&]+)(?:\s*[\W\s]*(?:\d+\.?\d*\s*[€$]|\s*$))?', caption, re.IGNORECASE)
    original_brand = brand_match.group(1).strip() if brand_match else None

    updated_caption = caption
    price_match = re.search(price_pattern, caption)
    if price_match:
        old_price = price_match.group(1)
        updated_caption = re.sub(
            r'\b' + re.escape(old_price) + r'\s*' + re.escape(price_match.group(2)),
            f"{new_price}{currency}",
            updated_caption
        )
    else:
        updated_caption = f"{updated_caption.strip()} {new_price}{currency}"

    percentage_match = re.search(percentage_pattern, caption)
    if percentage_match and new_percentage:
        updated_caption = re.sub(
            re.escape(percentage_match.group(0)),
            new_percentage,
            updated_caption
        )
    elif new_percentage:
        updated_caption = f"{updated_caption.strip()} {new_percentage}"
    elif percentage_match and not new_percentage:
        updated_caption = re.sub(
            re.escape(percentage_match.group(0)),
            '',
            updated_caption
        ).strip()

    if brand and original_brand and brand.lower() != original_brand.lower():
        updated_caption = re.sub(
            r'^\s*' + re.escape(original_brand) + r'\b',
            brand,
            updated_caption,
            flags=re.IGNORECASE
        )

    return updated_caption.strip()

async def send_with_retry(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except TelegramBadRequest as e:
            if "Too Many Requests" in str(e):
                delay = 2 ** (attempt + 1)
                print(f"DEBUG - Rate limit hit, retrying in {delay}s, attempt {attempt + 1}/{max_retries}")
                await asyncio.sleep(delay)
            else:
                raise
    raise TelegramBadRequest("Max retries reached due to rate limits")

async def queue_post(user_id, photo_ids, description, message_id, photo_count, batch_id, forward_from_message_id=None):
    if not photo_ids:
        print(
            f"DEBUG - Cannot queue post with empty photo_ids: user_id={user_id}, message_id={message_id}, batch_id={batch_id}")
        await bot.send_message(user_id, "Ошибка: отсутствуют фото для поста.")
        return False
    valid_photo_ids = [pid for pid in photo_ids if db.is_valid_file_id(pid)]
    if not valid_photo_ids:
        print(
            f"DEBUG - No valid photo IDs after validation: user_id={user_id}, message_id={message_id}, batch_id={batch_id}")
        await bot.send_message(user_id, "Ошибка: недействительные идентификаторы фото.")
        return False
    photo_ids_str = ','.join(sorted(valid_photo_ids))
    if db.check_queue_duplicate(user_id, valid_photo_ids, len(valid_photo_ids), description):
        print(
            f"DEBUG - Duplicate post detected: user_id={user_id}, batch_id={batch_id}, photo_ids={photo_ids_str}, photo_count={len(valid_photo_ids)}")
        await bot.send_message(user_id, "Этот пост уже отправлен.")
        return False
    try:
        db.queue_post(user_id, valid_photo_ids, description, message_id, len(valid_photo_ids), batch_id,
                      forward_from_message_id)
        print(
            f"DEBUG - Queued post: user_id={user_id}, message_id={message_id}, batch_id={batch_id}, photo_ids={photo_ids_str}, photo_count={len(valid_photo_ids)}")
        db.clear_pending_photos(user_id, batch_id=batch_id)
        return True
    except mysql.connector.Error as e:
        print(f"DEBUG - Error queuing post: {e}")
        await bot.send_message(user_id, f"Ошибка при добавлении поста в очередь: {str(e)}")
        return False

async def clear_stale_pending_photos(user_id):
    try:
        db.cursor.execute(
            "DELETE FROM pending_photos WHERE user_id = %s AND created_at < NOW() - INTERVAL 1 HOUR",
            (user_id,)
        )
        db.conn.commit()
        print(f"DEBUG - Cleared stale pending photos for user_id={user_id}")
    except Exception as e:
        print(f"Error clearing stale pending photos: {e}")

async def cleanup_stale_media_groups():
    while True:
        expired = [mg_id for mg_id, data in list(media_groups.items()) if time.time() - data['timestamp'] > 300]  # 5 minutes
        for mg_id in expired:
            if media_groups[mg_id]['timeout_task']:
                media_groups[mg_id]['timeout_task'].cancel()
            del media_groups[mg_id]
            print(f"DEBUG - Cleaned up stale media group: media_group_id={mg_id}")
        await asyncio.sleep(60)  # Check every minute

async def process_queue():
    while True:
        async with queue_lock:
            post = db.get_next_queued_post()
            if not post:
                await asyncio.sleep(1)
                continue
            post_id, user_id, photo_ids_str, photo_count, description, message_id, forward_from_message_id, batch_id = post
            photo_ids = [pid for pid in photo_ids_str.split(',') if db.is_valid_file_id(pid)]
            print(
                f"DEBUG - Processing queued post: post_id={post_id}, user_id={user_id}, batch_id={batch_id}, photo_ids={photo_ids}, photo_count={photo_count}")
            if not photo_ids or len(photo_ids) != photo_count:
                print(f"DEBUG - Invalid photo IDs or count for post_id={post_id}")
                db.update_queue_status(post_id, 'failed')
                await bot.send_message(user_id, f"Ошибка: недействительные фото для поста {post_id}.")
                await asyncio.sleep(5)
            else:
                try:
                    db.update_queue_status(post_id, 'processing')

                    class MockMessage:
                        def __init__(self, user_id, message_id, photo_ids, caption, forward_from_message_id):
                            self.message_id = message_id
                            self.from_user = type('User', (), {'id': user_id})()
                            self.chat = type('Chat', (), {'id': user_id})()
                            self.photo = [MockPhoto(file_id=pid) for pid in photo_ids]
                            self.caption = caption
                            self.forward_from = None
                            self.forward_from_chat = None
                            self.forward_from_message_id = forward_from_message_id

                        async def reply(self, text, **kwargs):
                            return await bot.send_message(chat_id=self.from_user.id, text=text, **kwargs)

                    class MockPhoto:
                        def __init__(self, file_id):
                            self.file_id = file_id
                            self.file_size = None

                    mock_message = MockMessage(user_id, message_id, photo_ids, description, forward_from_message_id)
                    await handle_photo_post(mock_message)
                    db.update_queue_status(post_id, 'sent')
                    print(f"DEBUG - Successfully processed queued post: post_id={post_id}, batch_id={batch_id}")
                    await bot.send_message(user_id,
                                           f"Пост отправлен: {description[:50]}{'...' if len(description) > 50 else ''}")
                    await asyncio.sleep(5)
                except Exception as e:
                    print(f"DEBUG - Error processing queued post {post_id}: {e}")
                    db.update_queue_status(post_id, 'failed')
                    await bot.send_message(user_id, f"Ошибка при обработке поста {post_id}: {str(e)}")
                    await asyncio.sleep(5)
            next_post = db.get_next_queued_post()
            if not next_post:
                try:
                    db.clear_post_queue()
                    print(f"DEBUG - Cleared post_queue as no pending posts remain")
                except Exception as e:
                    print(f"DEBUG - Error clearing post_queue: {e}")

@router.message(F.photo | F.forward_from | F.forward_from_chat | F.forward_from_message_id)
async def handle_photo(message: Message):
    is_forwarded = message.forward_from is not None or message.forward_from_chat is not None or message.forward_from_message_id is not None
    print(
        f"DEBUG - Processing message: message_id={message.message_id}, is_forwarded={is_forwarded}, has_photo={bool(message.photo)}, caption={message.caption or ''}, media_group_id={message.media_group_id or 'None'}, forward_from_message_id={message.forward_from_message_id or 'None'}")

    if message.photo:
        batch_id = str(uuid.uuid4()) + f"-{message.message_id}"  # Ensure unique batch_id per message
        photo_count = len(message.photo)
        print(
            f"DEBUG - Received photo(s): message_id={message.message_id}, batch_id={batch_id}, photo_count={photo_count}, photo_details={[(p.file_id, p.file_size) for p in message.photo]}")
        photo_ids = select_unique_photos(message.photo)
        if not photo_ids:
            print(f"DEBUG - No valid photo IDs after selection: message_id={message.message_id}, batch_id={batch_id}")
            await message.reply("Ошибка: недействительные идентификаторы фото.")
            return

        valid_photo_ids = [pid for pid in photo_ids if db.is_valid_file_id(pid)]
        if not valid_photo_ids:
            print(f"DEBUG - No valid photo IDs after validation: message_id={message.message_id}, batch_id={batch_id}")
            await message.reply("Ошибка: недействительные идентификаторы фото.")
            return

        if message.media_group_id:
            if message.media_group_id not in media_groups:
                media_groups[message.media_group_id] = {
                    'user_id': message.from_user.id,
                    'message_id': message.message_id,
                    'photo_ids': [],
                    'photo_count': 0,
                    'expected_count': photo_count,  # Track expected photos
                    'caption': message.caption or '',
                    'forward_from_message_id': message.forward_from_message_id,
                    'batch_id': batch_id,
                    'timeout_task': None,
                    'timestamp': message.date.timestamp()
                }
            media_groups[message.media_group_id]['photo_ids'].extend(valid_photo_ids)
            media_groups[message.media_group_id]['photo_ids'] = list(set(media_groups[message.media_group_id]['photo_ids']))
            media_groups[message.media_group_id]['photo_count'] = len(media_groups[message.media_group_id]['photo_ids'])
            if message.caption:
                media_groups[message.media_group_id]['caption'] = message.caption
            print(
                f"DEBUG - Added to media group: media_group_id={message.media_group_id}, batch_id={batch_id}, photo_ids={media_groups[message.media_group_id]['photo_ids']}, photo_count={media_groups[message.media_group_id]['photo_count']}, expected_count={media_groups[message.media_group_id]['expected_count']}")

            if media_groups[message.media_group_id]['timeout_task']:
                media_groups[message.media_group_id]['timeout_task'].cancel()

            async def process_media_group(mg_id):
                mg_data = media_groups.get(mg_id)
                if not mg_data:
                    return
                # Wait until all photos are collected or timeout
                start_time = time.time()
                while mg_data['photo_count'] < mg_data['expected_count'] and time.time() - start_time < 10:
                    await asyncio.sleep(0.5)
                valid_photo_ids = list(set(mg_data['photo_ids']))
                batch_id = mg_data['batch_id']
                if not valid_photo_ids:
                    print(f"DEBUG - No valid photo IDs in media group: media_group_id={mg_id}, batch_id={batch_id}")
                    await bot.send_message(mg_data['user_id'], "Ошибка: недействительные идентификаторы фото.")
                    del media_groups[mg_id]
                    return
                try:
                    await db.log_pending_photo(
                        mg_data['user_id'],
                        mg_data['message_id'],
                        valid_photo_ids,
                        batch_id=batch_id,
                        media_group_id=mg_id,
                        forward_from_message_id=mg_data['forward_from_message_id']
                    )
                    print(
                        f"DEBUG - Logged media group photos: message_id={mg_data['message_id']}, media_group_id={mg_id}, batch_id={batch_id}, photo_ids={valid_photo_ids}, photo_count={mg_data['photo_count']}, forward_from_message_id={mg_data['forward_from_message_id']}")
                    if mg_data['caption']:
                        if await queue_post(
                                mg_data['user_id'],
                                valid_photo_ids,
                                mg_data['caption'],
                                mg_data['message_id'],
                                len(valid_photo_ids),
                                batch_id,
                                mg_data['forward_from_message_id']
                        ):
                            await bot.send_message(mg_data['user_id'], "Пост добавлен в очередь для обработки.")
                        else:
                            await bot.send_message(mg_data['user_id'],
                                                   "Ошибка: пост уже в очереди или произошла ошибка.")
                    else:
                        await bot.send_message(mg_data['user_id'],
                                               "Фото получено. Пожалуйста, отправьте описание товара.")
                    del media_groups[mg_id]
                except Exception as e:
                    print(f"DEBUG - Error logging pending photos: {e}")
                    await bot.send_message(mg_data['user_id'], f"Ошибка при сохранении фото: {str(e)}")
                    del media_groups[mg_id]

            media_groups[message.media_group_id]['timeout_task'] = asyncio.create_task(
                process_media_group(message.media_group_id))
        else:
            if message.caption:
                if await queue_post(
                        message.from_user.id,
                        valid_photo_ids,
                        message.caption,
                        message.message_id,
                        len(valid_photo_ids),
                        batch_id,
                        message.forward_from_message_id
                ):
                    await message.reply("Пост добавлен в очередь для обработки.")
            else:
                try:
                    await db.log_pending_photo(
                        message.from_user.id,
                        message.message_id,
                        valid_photo_ids,
                        batch_id=batch_id,
                        media_group_id=None,
                        forward_from_message_id=message.forward_from_message_id
                    )
                    print(
                        f"DEBUG - Logged individual photo: message_id={message.message_id}, batch_id={batch_id}, photo_ids={valid_photo_ids}, photo_count={len(valid_photo_ids)}, forward_from_message_id={message.forward_from_message_id}")
                    await message.reply("Фото получено. Пожалуйста, отправьте описание товара.")
                except Exception as e:
                    print(f"DEBUG - Error logging pending photos: {e}")
                    await message.reply(f"Ошибка при сохранении фото: {str(e)}")
    else:
        if is_forwarded:
            if message.text or message.caption:
                print(
                    f"DEBUG - Forwarded message without photos, routing to handle_text: message_id={message.message_id}")
                await handle_text(message)
            else:
                print(f"DEBUG - Forwarded message with no photos or text: message_id={message.message_id}")
                await message.reply("Пожалуйста, перешлите сообщение с фото или текстовым описанием.")
        else:
            print(f"DEBUG - No photos in non-forwarded message: message_id={message.message_id}")
            await message.reply("Пожалуйста, отправьте фото или перешлите сообщение с фото.")

@router.message(F.text | F.forward_from | F.forward_from_chat | F.forward_from_message_id)
async def handle_text(message: Message):
    print(
        f"DEBUG - Received text: message_id={message.message_id}, text={message.text or 'None'}, forward_from_message_id={message.forward_from_message_id or 'None'}")
    user_id = message.from_user.id
    description = message.text or message.caption or ""
    is_forwarded = message.forward_from is not None or message.forward_from_chat is not None or message.forward_from_message_id is not None

    await clear_stale_pending_photos(user_id)

    max_attempts = 10
    for attempt in range(max_attempts):
        pending = db.get_pending_photos(user_id)
        if pending:
            break
        if attempt < max_attempts - 1:
            print(f"DEBUG - Attempt {attempt + 1}/{max_attempts}: No pending photos for user_id={user_id}, retrying...")
            await asyncio.sleep(2)
    if not pending:
        print(f"DEBUG - No pending photos found after retries for user_id={user_id}")
        await message.reply("Пожалуйста, сначала отправьте фото товара.")
        return

    batch_groups = {}
    for p in pending:
        message_id, photo_ids_str, media_group_id, forward_from_message_id, batch_id, created_at = p
        if batch_id not in batch_groups:
            batch_groups[batch_id] = []
        batch_groups[batch_id].append(
            (message_id, photo_ids_str, media_group_id, forward_from_message_id, batch_id, created_at))

    if not batch_groups:
        print(f"DEBUG - No batch groups formed for user_id={user_id}")
        await message.reply("Ошибка: не удалось найти ожидающие фото.")
        return

    # Prioritize batch matching
    selected_batch = None
    if is_forwarded and message.forward_from_message_id:
        # Exact match by forward_from_message_id
        for batch_id, batch in batch_groups.items():
            if any(p[3] == message.forward_from_message_id for p in batch):
                selected_batch = (batch_id, batch)
                print(
                    f"DEBUG - Selected batch by forward_from_message_id: user_id={user_id}, batch_id={batch_id}, forward_from_message_id={message.forward_from_message_id}")
                break
    if not selected_batch and message.media_group_id:
        # Match by media_group_id
        for batch_id, batch in batch_groups.items():
            if any(p[2] == message.media_group_id for p in batch):
                selected_batch = (batch_id, batch)
                print(
                    f"DEBUG - Selected batch by media_group_id: user_id={user_id}, batch_id={batch_id}, media_group_id={message.media_group_id}")
                break
    if not selected_batch:
        # Fallback to earliest created_at
        sorted_batches = sorted(
            batch_groups.items(),
            key=lambda x: min(p[5] for p in x[1])
        )
        selected_batch = sorted_batches[0]
        print(
            f"DEBUG - Selected earliest batch: user_id={user_id}, batch_id={selected_batch[0]}, photos_count={len(selected_batch[1])}")

    batch_id, pending_batch = selected_batch

    photo_ids = []
    message_ids = []
    selected_forward_from_message_id = None
    for p in sorted(pending_batch, key=lambda x: x[5]):
        msg_id, photo_ids_str, media_group_id, forward_id, _, _ = p
        photos = [pid for pid in photo_ids_str.split(',') if db.is_valid_file_id(pid)]
        if photos:
            photo_ids.extend(photos)
            message_ids.append(msg_id)
            if forward_id and not selected_forward_from_message_id:
                selected_forward_from_message_id = forward_id
    photo_ids = list(set(photo_ids))
    photo_count = len(photo_ids)
    latest_message_id = max(message_ids) if message_ids else message.message_id

    print(
        f"DEBUG - Processed batch: user_id={user_id}, batch_id={batch_id}, photo_ids={photo_ids}, photo_count={photo_count}, message_ids={message_ids}")
    if not photo_ids:
        print(f"DEBUG - No valid photo IDs in batch_id={batch_id}, user_id={user_id}")
        await message.reply("Ошибка: сохраненные изображения имеют невалидные идентификаторы.")
        db.clear_pending_photos(user_id, batch_id=batch_id)
        return

    if await queue_post(
            user_id,
            photo_ids,
            description,
            latest_message_id,
            photo_count,
            batch_id,
            message.forward_from_message_id if is_forwarded else selected_forward_from_message_id
    ):
        await message.reply("Пост добавлен в очередь для обработки.")
        print(f"DEBUG - Successfully queued post for batch_id={batch_id}, user_id={user_id}, photo_ids={photo_ids}")
    else:
        await message.reply("Ошибка: Пост уже в очереди или произошла ошибка.")
        print(f"DEBUG - Failed to queue post: user_id={user_id}, batch_id={batch_id}, photo_ids={photo_ids}")

async def handle_photo_post(message: Message):
    print(
        f"DEBUG - Processing photo post: message_id={message.message_id}, caption={message.caption or ''}, photo_count={len(message.photo) if message.photo else 0}")
    description = message.caption or ""
    photo_ids = select_unique_photos(message.photo) if message.photo else []
    print(f"DEBUG - Processed photo IDs: {photo_ids}, count={len(photo_ids)}")
    if not photo_ids:
        print(f"DEBUG - No valid photo IDs in handle_photo_post: message_id={message.message_id}")
        await message.reply("Ошибка: Недействительные идентификаторы фото.")
        return
    existing_post = db.get_post_by_message_id(message.message_id)
    if existing_post:
        print(f"DEBUG - Post with message_id={message.message_id} already exists, skipping")
        return
    brand_match = re.search(r'^\s*([A-Za-z\s&]+)(?:\s*[\W\s]*(?:\d+\.?\d*\s*[€$]|\s*$))?', description, re.IGNORECASE)
    brand = brand_match.group(1).strip() if brand_match else "Unknown"
    price_match = re.search(r'(\d+\.?\d*)\s*([€$])', description)
    price = float(price_match.group(1)) if price_match else None
    currency = price_match.group(2) if price_match else '€'
    sizes = extract_sizes(description)
    percentage_match = re.search(r'([-+]\d+%?)', description)
    original_percentage = percentage_match.group(0) if percentage_match else None
    print(f"DEBUG - Extracted: brand={brand}, price={price}, currency={currency}, sizes={sizes}, original_percentage={original_percentage}")
    is_forwarded = message.forward_from is not None or message.forward_from_chat is not None or message.forward_from_message_id is not None
    corrected_brand, target_groups, target_topic = db.get_corrected_brand(brand.lower())
    if corrected_brand == "Unknown" and brand != "Unknown":
        cleaned_brand = re.sub(r'[^\w\s]', '', brand.lower())
        corrected_brand, target_groups, target_topic = db.get_corrected_brand(cleaned_brand)
    print(f"DEBUG - Corrected brand: {corrected_brand}")
    if is_forwarded and message.forward_from_message_id:
        db.clear_stale_forwarded_posts(message.from_user.id)
        post = None
        if message.forward_from_message_id:
            post = db.get_post_by_forward_from_message_id(message.forward_from_message_id)
        if not post and price:
            post = db.get_post_by_caption(corrected_brand, price)
        if not post and photo_ids:
            post = db.get_post_by_photo_id(photo_ids[0], corrected_brand)
        if not post:
            await message.reply("Исходный пост не найден.")
            print(f"DEBUG - No post found for forwarded post")
            return
        brand, current_price, original_price, photo_ids_db, client_message_id, client_chat_id, client_topic_name, sizes_db = post
        print(f"DEBUG - Found post: client_message_id={client_message_id}")
        if not client_message_id or not client_chat_id:
            await message.reply("В посте отсутствуют данные для обновления.")
            return
        if not original_price:
            await message.reply("Отсутствует исходная цена.")
            return
        adjusted_price, percentage, adjusted_currency = adjust_price(description) if config["adjust_price"] else (
            original_price, None, currency)
        if not adjusted_price:
            await message.reply("Не удалось определить цену.")
            return
        client_percentage = f"{percentage}" if percentage else None
        client_caption = update_caption_price_and_percentage(description, adjusted_price, client_percentage,
                                                             adjusted_currency, corrected_brand)
        try:
            await bot.delete_message(chat_id=client_chat_id, message_id=client_message_id)
            await asyncio.sleep(5)
            if len(photo_ids) > 1:
                media_group = [
                    InputMediaPhoto(media=pid, caption=client_caption if i == 0 else None)
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
                    caption=client_caption,
                    message_thread_id=db.get_topic_thread_id(client_chat_id, client_topic_name)
                )
                new_client_message_id = sent_message.message_id
            db.update_post_price(new_client_message_id, adjusted_price, percentage)
            print(f"DEBUG - Replaced client post {client_message_id} with new message_id={new_client_message_id}")
            post = db.get_post_by_client_message_id(client_message_id)
            if post:
                _, _, _, _, _, _, _, _, buyer_message_ids_str = post
                if buyer_message_ids_str:
                    buyer_message_ids = buyer_message_ids_str.split(',')
                    buyer_price = original_price
                    buyer_currency = adjusted_currency
                    buyer_caption = update_caption_price_and_percentage(description, buyer_price, original_percentage,
                                                                        buyer_currency, corrected_brand)
                    for idx, buyer_group in enumerate(config["forward_to_buyers"]):
                        if idx < len(buyer_message_ids):
                            buyer_message_id = buyer_message_ids[idx]
                            buyer_chat_id = db.get_group_info(buyer_group)
                            if buyer_chat_id:
                                try:
                                    await bot.delete_message(chat_id=buyer_chat_id, message_id=int(buyer_message_id))
                                    await asyncio.sleep(5)
                                    if len(photo_ids) > 1:
                                        media_group = [
                                            InputMediaPhoto(media=pid, caption=buyer_caption if i == 0 else None)
                                            for i, pid in enumerate(photo_ids)
                                        ]
                                        sent_buyer = await send_with_retry(
                                            bot.send_media_group,
                                            chat_id=buyer_chat_id,
                                            media=media_group
                                        )
                                        new_buyer_message_id = sent_buyer[0].message_id
                                    else:
                                        sent_buyer_message = await send_with_retry(
                                            bot.send_photo,
                                            chat_id=buyer_chat_id,
                                            photo=photo_ids[0],
                                            caption=buyer_caption
                                        )
                                        new_buyer_message_id = sent_buyer_message.message_id
                                    buyer_message_ids[idx] = str(new_buyer_message_id)
                                    print(f"DEBUG - Replaced buyer post in {buyer_group}")
                                    await asyncio.sleep(5)
                                except TelegramBadRequest as e:
                                    print(f"DEBUG - Error updating buyer post: {e}")
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
                caption=client_caption,
                forward_from_message_id=message.forward_from_message_id,
                client_message_id=new_client_message_id
            )
            db.delete_forwarded_post(message.message_id)
            await message.reply(f"Пост успешно обработан: {client_caption}")
            await forward_to_buyers(
                message,
                photo_ids,
                corrected_brand,
                buyer_price,
                sizes,
                config["forward_to_buyers"],
                new_client_message_id,
                buyer_caption
            )
        except TelegramBadRequest as e:
            print(f"DEBUG - Telegram error updating post: {e}")
            await message.reply(f"Ошибка при отправке поста: {str(e)}")
            db.delete_forwarded_post(message.message_id)
        return
    if config["sort_by_brand"]:
        if corrected_brand == "Unknown":
            await message.reply("Не удалось определить бренд.")
            return
        if not target_groups or not target_topic:
            await message.reply(f"Группа или тема не найдены для бренда: {corrected_brand}")
            return
        target_group = target_groups[0]
    else:
        target_group = config["target_group"]
        target_topic = config["target_topic"]
        if not target_group or not target_topic:
            await message.reply("Отсутствует конфигурация группы или темы.")
            return
    existing_posts = db.get_existing_posts(corrected_brand, photo_ids, price, message.message_id)
    if existing_posts:
        for client_message_id, client_chat_id, client_topic_name, _, existing_sizes in existing_posts:
            adjusted_price, percentage, adjusted_currency = adjust_price(description) if config["adjust_price"] else (
                price, None, currency)
            if not adjusted_price:
                await message.reply("Не удалось определить цену для обновления поста.")
                return
            client_percentage = f"{percentage}" if percentage else None
            client_caption = update_caption_price_and_percentage(description, adjusted_price, client_percentage,
                                                                 adjusted_currency, corrected_brand)
            try:
                await bot.edit_message_caption(
                    chat_id=client_chat_id,
                    message_id=client_message_id,
                    caption=client_caption
                )
                db.update_post_price(client_message_id, adjusted_price, percentage)
                buyer_price = price
                buyer_currency = currency
                buyer_caption = update_caption_price_and_percentage(description, buyer_price, original_percentage,
                                                                    buyer_currency, corrected_brand)
                await forward_to_buyers(
                    message,
                    photo_ids,
                    corrected_brand,
                    buyer_price,
                    sizes,
                    config["forward_to_buyers"],
                    client_message_id,
                    buyer_caption
                )
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    await message.reply("Описание поста не изменено.")
                else:
                    await message.reply(f"Ошибка при обновлении поста: {str(e)}")
                return
    watermarked_photos = []
    watermarked_photo_ids = [None] * len(photo_ids)
    if config.get("add_watermark"):
        for i, photo_id in enumerate(photo_ids):
            try:
                photo_data = await download_photo(photo_id, bot)
                watermarked_data = await add_watermark(photo_data, target_group)
                watermarked_file = BufferedInputFile(watermarked_data, filename=f"photo_{i}.jpg")
                watermarked_photos.append(watermarked_file)
            except Exception as e:
                print(f"ERROR - Failed watermarking photo {photo_id}: {e}")
                watermarked_photos.append(photo_id)
    else:
        watermarked_photos = photo_ids.copy()
    chat_id = db.get_group_info(target_group)
    if not chat_id:
        await message.reply(f"Группа {target_group} не найдена.")
        return
    message_thread_id = db.get_topic_thread_id(target_group, target_topic)
    print(
        f"DEBUG - Sending to client group: {target_group}, chat_id={chat_id}, topic={target_topic}, message_thread_id={message_thread_id}, photo_count={len(photo_ids)}")

    adjusted_price, percentage, adjusted_currency = adjust_price(description) if config["adjust_price"] else (
        price, None, currency)
    if not adjusted_price:
        await message.reply("Не удалось определить цену для поста.")
        return
    client_percentage = f"{percentage}" if percentage else None
    client_caption = update_caption_price_and_percentage(description, adjusted_price, client_percentage,
                                                         adjusted_currency, corrected_brand)
    try:
        await asyncio.sleep(5)
        if len(watermarked_photos) > 1:
            media_group = [
                InputMediaPhoto(media=photo, caption=client_caption if i == 0 else None)
                for i, photo in enumerate(watermarked_photos)
            ]
            sent_messages = await send_with_retry(
                bot.send_media_group,
                chat_id=chat_id,
                media=media_group,
                message_thread_id=message_thread_id
            )
            sent_message = sent_messages[0]
            if config["add_watermark"]:
                watermarked_photo_ids = [msg.photo[-1].file_id for msg in sent_messages if msg.photo]
        else:
            sent_message = await send_with_retry(
                bot.send_photo,
                chat_id=chat_id,
                photo=watermarked_photos[0],
                caption=client_caption,
                message_thread_id=message_thread_id
            )
            if config["add_watermark"] and sent_message.photo:
                watermarked_photo_ids[0] = sent_message.photo[-1].file_id
        print(f"DEBUG - Successfully sent to client group {target_group}: message_id={sent_message.message_id}")
        await asyncio.sleep(5)
        buyer_price = price
        buyer_currency = currency
        buyer_caption = update_caption_price_and_percentage(description, buyer_price, original_percentage, buyer_currency, corrected_brand)
        await forward_to_buyers(
            message,
            photo_ids,
            corrected_brand,
            buyer_price,
            sizes,
            config["forward_to_buyers"],
            sent_message.message_id,
            buyer_caption
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
        print(f"DEBUG - Error sending to client group {target_group}: {e}")
        await message.reply(f"Ошибка при отправке в пост: {str(e)}")
        raise

async def forward_to_buyers(message, photo_ids, corrected_brand, price, sizes, buyer_groups, client_message_id,
                            full_caption=None):
    buyer_message_ids = []
    for buyer in buyer_groups:
        buyer_chat_id = db.get_group_info(buyer)
        if not buyer_chat_id:
            print(f"DEBUG - Buyer group {buyer} not found")
            continue
        buyer_caption = full_caption.strip() if full_caption else ""
        print(f"DEBUG - Sending to buyer_group: {buyer}, chat_id={buyer_chat_id}, photo_count={len(photo_ids)}")
        try:
            await asyncio.sleep(5)
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
            print(f"Successfully sent to buyer group: {buyer}")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error sending to buyer group {buyer}: {str(e)}")
            continue
    if buyer_message_ids:
        try:
            buyer_message_ids_str = ','.join(map(str, buyer_message_ids))
            db.cursor.execute(
                "UPDATE posts SET buyer_message_ids = %s WHERE client_message_id = %s",
                (buyer_message_ids_str, client_message_id)
            )
            db.conn.commit()
            print(f"Successfully updated buyer_message_ids for client_message_id={client_message_id}")
        except Exception as e:
            print(f"Error updating buyer_message_ids: {e}")

async def main():
    print(f"Bot {BOT_NAME} started!")
    asyncio.create_task(process_queue())
    asyncio.create_task(cleanup_stale_media_groups())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print(f"Bot {BOT_NAME} stopped!")
        db.close()