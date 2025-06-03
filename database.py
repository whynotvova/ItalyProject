import re
import mysql.connector
import uuid
import unicodedata
from config import MYSQL_CONFIG, KNOWN_BRANDS, BRAND_ABBREVIATIONS

class Database:
    def __init__(self):
        try:
            self.conn = mysql.connector.connect(**MYSQL_CONFIG)
            self.cursor = self.conn.cursor()
        except mysql.connector.Error as e:
            print(f"Error connecting to database: {e}")
            raise

    def is_valid_file_id(self, file_id):
        return bool(file_id and isinstance(file_id, str) and len(file_id) > 20 and re.match(r'^[A-Za-z0-9_-]+$', file_id))

    def get_corrected_brand(self, input_brand):
        input_brand = unicodedata.normalize('NFKD', input_brand.lower()).encode('ASCII', 'ignore').decode('utf-8')
        input_brand = input_brand.replace('с', 'c').strip()
        print(f"Debug - Normalized brand: {input_brand}")

        if input_brand == 'man':
            print(f"Debug - Input is 'man', returning unchanged")
            self.cursor.execute(
                "SELECT corrected_name, target_groups, target_topic FROM brands WHERE input_name = %s OR corrected_name = %s",
                (input_brand, input_brand)
            )
            result = self.cursor.fetchone()
            if result:
                print(f"Debug - Found match in database for 'man': {result}")
                target_groups = result[1].split(',') if result[1] else []
                return result[0], target_groups, result[2]
            return 'Man', [], None

        try:
            if input_brand in BRAND_ABBREVIATIONS:
                corrected_brand = BRAND_ABBREVIATIONS[input_brand].lower()
                print(f"Debug - Matched abbreviation: {input_brand} → {corrected_brand}")
                self.cursor.execute(
                    "SELECT corrected_name, target_groups, target_topic FROM brands WHERE input_name = %s OR corrected_name = %s",
                    (corrected_brand, corrected_brand)
                )
                result = self.cursor.fetchone()
                if result:
                    print(f"Debug - Found match in database for abbreviation: {result}")
                    target_groups = result[1].split(',') if result[1] else []
                    return result[0], target_groups, result[2]
                return corrected_brand, [], None

            self.cursor.execute(
                "SELECT corrected_name, target_groups, target_topic FROM brands WHERE input_name = %s OR corrected_name = %s",
                (input_brand, input_brand)
            )
            result = self.cursor.fetchone()
            if result:
                print(f"Debug - Found exact match in database: {input_brand} → {result[0]}")
                target_groups = result[1].split(',') if result[1] else []
                return result[0], target_groups, result[2]

            for brand in KNOWN_BRANDS:
                if brand.lower().startswith(input_brand):
                    print(f"Debug - Prefix match: input={input_brand}, brand={brand}")
                    self.cursor.execute(
                        "SELECT corrected_name, target_groups, target_topic FROM brands WHERE corrected_name = %s",
                        (brand,)
                    )
                    result = self.cursor.fetchone()
                    if result:
                        print(f"Debug - Found in database after prefix match: {result}")
                        target_groups = result[1].split(',') if result[1] else []
                        return result[0], target_groups, result[2]
                    return brand, [], None

            from fuzzywuzzy import fuzz
            best_match = max(KNOWN_BRANDS, key=lambda x: fuzz.partial_ratio(input_brand, x.lower()), default="Unknown")
            match_score = fuzz.partial_ratio(input_brand, best_match.lower()) if best_match != "Unknown" else 0
            print(f"Debug - Fuzzy match: input={input_brand}, best_match={best_match}, score={match_score}")
            if best_match != "Unknown" and match_score > 80:
                self.cursor.execute(
                    "SELECT corrected_name, target_groups, target_topic FROM brands WHERE corrected_name = %s",
                    (best_match,)
                )
                result = self.cursor.fetchone()
                if result:
                    print(f"Debug - Found in database after fuzzy match: {result}")
                    target_groups = result[1].split(',') if result[1] else []
                    return result[0], target_groups, result[2]
                return best_match, [], None

            return "Unknown", [], None
        except mysql.connector.Error as e:
            print(f"Error in get_corrected_brand: {e}")
            raise

    def get_group_info(self, group_name):
        try:
            self.cursor.execute(
                "SELECT group_id FROM groupss WHERE group_name = %s",
                (group_name,)
            )
            result = self.cursor.fetchone()
            print(f"Group info for {group_name}: {result}")
            return result[0] if result else None
        except mysql.connector.Error as e:
            print(f"Error fetching group info for {group_name}: {e}")
            raise

    def get_topic_thread_id(self, group_name, target_topic):
        try:
            self.cursor.execute(
                "SELECT message_thread_id FROM topics WHERE group_name = %s AND target_topic = %s",
                (group_name, target_topic)
            )
            result = self.cursor.fetchone()
            print(f"Topic thread ID for {group_name}, {target_topic}: {result}")
            return result[0] if result else None
        except mysql.connector.Error as e:
            print(f"Error fetching topic thread ID for {group_name}, {target_topic}: {e}")
            raise

    def get_post_by_message_id(self, message_id):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE message_id = %s",
                (message_id,)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_message_id: {e}")
            raise

    def get_post_by_client_message_id(self, client_message_id):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes, buyer_message_ids "
                "FROM posts WHERE client_message_id = %s",
                (client_message_id,)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_client_message_id: {e}")
            raise

    def get_post_by_forward_from_message_id(self, forward_from_message_id):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE forward_from_message_id = %s OR client_message_id = %s",
                (forward_from_message_id, forward_from_message_id)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_forward_from_message_id: {e}")
            raise

    def get_post_by_photo_id(self, photo_id, brand):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE (photo_ids LIKE %s OR watermarked_photo_ids LIKE %s) AND brand = %s AND client_message_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (f'%{photo_id}%', f'%{photo_id}%', brand)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_photo_id: {e}")
            raise

    def get_client_message_id_by_photo_id(self, photo_id, brand):
        try:
            self.cursor.execute(
                "SELECT client_message_id "
                "FROM posts WHERE (photo_ids LIKE %s OR watermarked_photo_ids LIKE %s) AND brand = %s AND client_message_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (f'%{photo_id}%', f'%{photo_id}%', brand)
            )
            result = self.cursor.fetchone()
            return result[0] if result else None
        except mysql.connector.Error as e:
            print(f"Error in get_client_message_id_by_photo_id: {e}")
            raise

    def get_post_by_caption(self, brand, price):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE brand = %s AND (original_price = %s OR price = %s) AND client_message_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (brand, price, price)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_caption: {e}")
            raise

    def get_post_by_photo_ids_and_brand(self, photo_ids, brand):
        photo_ids_str = ','.join(photo_ids)
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE brand = %s AND photo_ids = %s AND client_message_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (brand, photo_ids_str)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_photo_ids_and_brand: {e}")
            raise

    def get_post_by_brand_and(self, brand):
        try:
            self.cursor.execute(
                "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "
                "FROM posts WHERE brand = %s AND client_message_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (brand,)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_post_by_brand_and: {e}")
            raise

    def log_post(self, bot_name, message_id, brand, price, adjusted_price, sizes, photo_ids, client_message_id=None,
                 client_chat_id=None, client_topic_name=None, forward_from_message_id=None, watermarked_photo_ids=None,
                 buyer_message_ids=None):
        try:
            original_price = float(price) / (1 + int(float(adjusted_price.strip('%'))) / 100) if adjusted_price else float(
                price)
            buyer_message_ids_str = ','.join(map(str, buyer_message_ids)) if buyer_message_ids else None
            self.cursor.execute(
                "INSERT INTO posts (bot_name, message_id, brand, price, original_price, adjusted_price, sizes, photo_ids, client_message_id, client_chat_id, client_topic_name, forward_from_message_id, watermarked_photo_ids, buyer_message_ids) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (bot_name, message_id, brand, float(price), original_price, adjusted_price, sizes, photo_ids,
                 client_message_id, client_chat_id, client_topic_name, forward_from_message_id, watermarked_photo_ids,
                 buyer_message_ids_str)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error logging post: {e}")
            self.conn.rollback()
            raise

    def get_existing_posts(self, brand, photo_ids, price=None, forward_from_message_id=None):
        photo_ids_str = ','.join(photo_ids)
        try:
            if forward_from_message_id:
                self.cursor.execute(
                    "SELECT client_message_id, client_chat_id, client_topic_name, adjusted_price, sizes "
                    "FROM posts WHERE (forward_from_message_id = %s OR client_message_id = %s) AND client_message_id IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (forward_from_message_id, forward_from_message_id)
                )
            elif price:
                self.cursor.execute(
                    "SELECT client_message_id, client_chat_id, client_topic_name, adjusted_price, sizes "
                    "FROM posts WHERE brand = %s AND (photo_ids = %s OR watermarked_photo_ids = %s) AND (price = %s OR original_price = %s) AND client_message_id IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (brand, photo_ids_str, photo_ids_str, price, price)
                )
            else:
                self.cursor.execute(
                    "SELECT client_message_id, client_chat_id, client_topic_name, adjusted_price, sizes "
                    "FROM posts WHERE brand = %s AND (photo_ids = %s OR watermarked_photo_ids = %s) AND client_message_id IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (brand, photo_ids_str, photo_ids_str)
                )
            return self.cursor.fetchall()
        except mysql.connector.Error as e:
            print(f"Error in get_existing_posts: {e}")
            raise

    async def log_pending_photo(self, user_id, message_id, photo_ids, batch_id=None, media_group_id=None,
                                forward_from_message_id=None):
        print(
            f"Debug - log_pending_photo called with: user_id={user_id}, message_id={message_id}, photo_ids={photo_ids}, batch_id={batch_id}, media_group_id={media_group_id}, forward_from_message_id={forward_from_message_id}")
        try:
            valid_photo_ids = [pid for pid in photo_ids if self.is_valid_file_id(pid)]
            if not valid_photo_ids:
                print(f"Debug - No valid photo_ids provided: {photo_ids}")
                raise ValueError("No valid photo IDs provided")
            valid_photo_ids = list(set(valid_photo_ids))
            photo_ids_str = ','.join(valid_photo_ids)
            batch_id = batch_id or str(uuid.uuid4())
            self.cursor.execute(
                "DELETE FROM pending_photos WHERE user_id = %s AND (batch_id = %s OR (media_group_id = %s AND media_group_id IS NOT NULL))",
                (user_id, batch_id, media_group_id)
            )
            self.conn.commit()
            self.cursor.execute(
                "INSERT INTO pending_photos (user_id, message_id, photo_ids, batch_id, media_group_id, forward_from_message_id, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (user_id, message_id, photo_ids_str, batch_id, media_group_id, forward_from_message_id)
            )
            self.conn.commit()
            print(
                f"Debug - Logged photo: user_id={user_id}, message_id={message_id}, batch_id={batch_id}, photos={photo_ids_str}, media_group_id={media_group_id}, forward_from_message_id={forward_from_message_id}")
        except mysql.connector.Error as e:
            print(f"Debug - Database error logging pending photos: {e}")
            self.conn.rollback()
            raise
        except ValueError as e:
            print(f"Debug - Error logging pending photos: {e}")
            raise

    def get_pending_photos(self, user_id, media_group_id=None, batch_id=None):
        try:
            self.cursor.execute(
                "DELETE FROM pending_photos WHERE user_id = %s AND created_at < NOW() - INTERVAL 5 MINUTE",
                (user_id,)
            )
            self.conn.commit()
            if batch_id:
                self.cursor.execute(
                    "SELECT message_id, photo_ids, media_group_id, forward_from_message_id, batch_id, created_at "
                    "FROM pending_photos WHERE user_id = %s AND batch_id = %s ORDER BY created_at ASC",
                    (user_id, batch_id)
                )
            elif media_group_id:
                self.cursor.execute(
                    "SELECT message_id, photo_ids, media_group_id, forward_from_message_id, batch_id, created_at "
                    "FROM pending_photos WHERE user_id = %s AND media_group_id = %s ORDER BY created_at ASC",
                    (user_id, media_group_id)
                )
            else:
                self.cursor.execute(
                    "SELECT message_id, photo_ids, media_group_id, forward_from_message_id, batch_id, created_at "
                    "FROM pending_photos WHERE user_id = %s ORDER BY created_at ASC",
                    (user_id,)
                )
            results = self.cursor.fetchall()
            print(f"Debug - Fetched pending photos for user_id={user_id}: count={len(results)}")
            return results
        except mysql.connector.Error as e:
            print(f"Debug - Error fetching pending photos: {e}")
            return []

    def clear_pending_photos(self, user_id, batch_id=None, media_group_id=None, message_id=None):
        try:
            query = "DELETE FROM pending_photos WHERE user_id = %s"
            params = [user_id]
            if batch_id:
                query += " AND batch_id = %s"
                params.append(batch_id)
            if message_id:
                query += " AND message_id = %s"
                params.append(message_id)
            if media_group_id:
                query += " AND media_group_id = %s"
                params.append(media_group_id)
            self.cursor.execute(query, params)
            self.conn.commit()
            print(
                f"Debug - Cleared pending photos: user_id={user_id}, batch_id={batch_id}, message_id={message_id}, media_group_id={media_group_id}")
        except mysql.connector.Error as e:
            print(f"Debug - Error clearing pending_photos: {e}")
            self.conn.rollback()
            raise

    def queue_post(self, user_id, photo_ids, description, message_id, photo_count, batch_id=None,
                   forward_from_message_id=None):
        try:
            if not photo_ids:
                raise ValueError("photo_ids cannot be empty")
            photo_ids_str = ','.join(photo_ids)
            self.cursor.execute(
                "SELECT id FROM post_queue WHERE user_id = %s AND batch_id = %s",
                (user_id, batch_id)
            )
            if self.cursor.fetchone():
                print(f"Debug - Duplicate batch_id detected: user_id={user_id}, batch_id={batch_id}")
                raise ValueError("Duplicate batch_id in post_queue")
            self.cursor.execute(
                "INSERT INTO post_queue (user_id, photo_ids, photo_ids_str, description, photo_count, message_id, status, batch_id, forward_from_message_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, photo_ids_str, photo_ids_str, description, photo_count, message_id, 'pending', batch_id,
                 forward_from_message_id)
            )
            self.conn.commit()
            print(f"Debug - Queued post: user_id={user_id}, message_id={message_id}, batch_id={batch_id}, photo_count={photo_count}")
        except mysql.connector.Error as e:
            print(f"Error queuing post: {e}")
            self.conn.rollback()
            raise
        except ValueError as e:
            print(f"Error queuing post: {e}")
            raise

    def check_queue_duplicate(self, user_id, photo_ids, photo_count, description):
        try:
            photo_ids_str = ','.join(photo_ids)
            self.cursor.execute(
                "SELECT id FROM post_queue WHERE user_id = %s AND photo_ids_str = %s AND photo_count = %s AND description = %s",
                (user_id, photo_ids_str, photo_count, description)
            )
            result = self.cursor.fetchone()
            return result is not None
        except mysql.connector.Error as e:
            print(f"Error in check_queue_duplicate: {e}")
            raise

    def check_queue_by_message_id(self, user_id, message_id):
        try:
            self.cursor.execute(
                "SELECT id FROM post_queue WHERE user_id = %s AND message_id = %s",
                (user_id, message_id)
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in check_queue_by_message_id: {e}")
            raise

    def get_next_queued_post(self):
        try:
            self.cursor.execute(
                "SELECT id, user_id, photo_ids_str, photo_count, description, message_id, forward_from_message_id, batch_id "
                "FROM post_queue WHERE status = 'pending' ORDER BY timestamp ASC LIMIT 1"
            )
            return self.cursor.fetchone()
        except mysql.connector.Error as e:
            print(f"Error in get_next_queued_post: {e}")
            raise

    def update_queue_status(self, post_id, status):
        try:
            self.cursor.execute(
                "UPDATE post_queue SET status = %s WHERE id = %s",
                (status, post_id)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error updating queue status for post_id={post_id}: {e}")
            self.conn.rollback()
            raise

    def clear_post_queue(self):
        try:
            self.cursor.execute("DELETE FROM post_queue")
            self.conn.commit()
            print(f"Debug - Cleared all posts from post_queue")
        except mysql.connector.Error as e:
            print(f"Error clearing post_queue: {e}")
            self.conn.rollback()
            raise

    def update_post_price(self, client_message_id, price, adjusted_price):
        try:
            self.cursor.execute(
                "UPDATE posts SET price = %s, adjusted_price = %s WHERE client_message_id = %s",
                (price, adjusted_price, client_message_id)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error updating post_price: {e}")
            self.conn.rollback()
            raise

    def log_forwarded_post(self, user_id, bot_name, message_id, brand, photo_ids, caption, forward_from_message_id,
                           client_message_id):
        try:
            photo_ids_str = ','.join(photo_ids)
            self.cursor.execute(
                "INSERT INTO forwarded_posts (user_id, bot_name, message_id, brand, photo_ids, caption, forward_from_message_id, client_message_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, bot_name, message_id, brand, photo_ids_str, caption, forward_from_message_id, client_message_id)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error logging forwarded_post: {e}")
            self.conn.rollback()
            raise

    def delete_forwarded_post(self, message_id):
        try:
            self.cursor.execute(
                "DELETE FROM forwarded_posts WHERE message_id = %s",
                (message_id,)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error deleting forwarded_post: {e}")
            self.conn.rollback()
            raise

    def clear_stale_forwarded_posts(self, user_id):
        try:
            self.cursor.execute(
                "DELETE FROM forwarded_posts WHERE user_id = %s AND timestamp < NOW() - INTERVAL 1 DAY",
                (user_id,)
            )
            self.conn.commit()
        except mysql.connector.Error as e:
            print(f"Error clearing stale forwarded_posts: {e}")
            self.conn.rollback()
            raise

    def close(self):
        try:
            self.cursor.close()
            self.conn.close()
        except mysql.connector.Error as e:
            print(f"Error closing database: {e}")