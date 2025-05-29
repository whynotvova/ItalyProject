import re

import mysql.connector

import unicodedata

from config import MYSQL_CONFIG, KNOWN_BRANDS



class Database:

    def __init__(self):

        try:

            self.conn = mysql.connector.connect(**MYSQL_CONFIG)

            self.cursor = self.conn.cursor()

        except mysql.connector.Error as e:

            print(f"Error connecting to database: {e}")

            raise



    def get_corrected_brand(self, input_brand):

        # Normalize input: replace Cyrillic 'с' with 'c' and decompose Unicode

        input_brand = unicodedata.normalize('NFKD', input_brand.lower()).encode('ASCII', 'ignore').decode('ASCII')

        input_brand = input_brand.replace('с', 'c')

        print(f"Debug - Normalized brand: {input_brand}")



        self.cursor.execute(

            "SELECT corrected_name, target_groups, target_topic FROM brands WHERE input_name = %s",

            (input_brand,)

        )

        result = self.cursor.fetchone()

        if result:

            print(f"Found in database: {result}")

            target_groups = result[1].split(',') if result[1] else []

            return result[0], target_groups, result[2]

        from fuzzywuzzy import fuzz

        best_match = max(KNOWN_BRANDS, key=lambda x: fuzz.partial_ratio(input_brand, x.lower()), default="Unknown")

        print(f"Best match for '{input_brand}': {best_match}")

        if best_match != "Unknown":

            self.cursor.execute(

                "SELECT corrected_name, target_groups, target_topic FROM brands WHERE corrected_name = %s",

                (best_match,)

            )

            result = self.cursor.fetchone()

            if result:

                print(f"Found in database after fuzzy match: {result}")

                target_groups = result[1].split(',') if result[1] else []

                return result[0], target_groups, result[2]

        return input_brand, [], None



    def get_group_info(self, group_name):

        self.cursor.execute(

            "SELECT group_id FROM `groupss` WHERE group_name = %s",

            (group_name,)

        )

        result = self.cursor.fetchone()

        print(f"Group info for {group_name}: {result}")

        return result[0] if result else None



    def get_topic_thread_id(self, group_name, target_topic):

        self.cursor.execute(

            "SELECT message_thread_id FROM topics WHERE group_name = %s AND target_topic = %s",

            (group_name, target_topic)

        )

        result = self.cursor.fetchone()

        print(f"Topic thread ID for {group_name}, {target_topic}: {result}")

        return result[0] if result else None



    def get_post_by_message_id(self, message_id):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE message_id = %s",

            (message_id,)

        )

        return self.cursor.fetchone()



    def get_post_by_client_message_id(self, client_message_id):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes, buyer_message_ids "

            "FROM posts WHERE client_message_id = %s",

            (client_message_id,)

        )

        return self.cursor.fetchone()



    def get_post_by_forward_from_message_id(self, forward_from_message_id):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE forward_from_message_id = %s OR client_message_id = %s",

            (forward_from_message_id, forward_from_message_id)

        )

        return self.cursor.fetchone()



    def get_post_by_photo_id(self, photo_id, brand):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE (photo_ids LIKE %s OR watermarked_photo_ids LIKE %s) AND brand = %s AND client_message_id IS NOT NULL "

            "ORDER BY timestamp DESC LIMIT 1",

            (f'%{photo_id}%', f'%{photo_id}%', brand)

        )

        return self.cursor.fetchone()



    def get_client_message_id_by_photo_id(self, photo_id, brand):

        self.cursor.execute(

            "SELECT client_message_id "

            "FROM posts WHERE (photo_ids LIKE %s OR watermarked_photo_ids LIKE %s) AND brand = %s AND client_message_id IS NOT NULL "

            "ORDER BY timestamp DESC LIMIT 1",

            (f'%{photo_id}%', f'%{photo_id}%', brand)

        )

        result = self.cursor.fetchone()

        return result[0] if result else None



    def get_post_by_caption(self, brand, price):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE brand = %s AND (original_price = %s OR price = %s) AND client_message_id IS NOT NULL "

            "ORDER BY timestamp DESC LIMIT 1",

            (brand, price, price)

        )

        return self.cursor.fetchone()



    def get_post_by_photo_ids_and_brand(self, photo_ids, brand):

        photo_ids_str = ','.join(photo_ids)

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE brand = %s AND photo_ids = %s AND client_message_id IS NOT NULL "

            "ORDER BY timestamp DESC LIMIT 1",

            (brand, photo_ids_str)

        )

        return self.cursor.fetchone()



    def get_post_by_brand_and_price(self, brand):

        self.cursor.execute(

            "SELECT brand, price, original_price, photo_ids, client_message_id, client_chat_id, client_topic_name, sizes "

            "FROM posts WHERE brand = %s AND client_message_id IS NOT NULL "

            "ORDER BY timestamp DESC LIMIT 1",

            (brand,)

        )

        return self.cursor.fetchone()



    def log_post(self, bot_name, message_id, brand, price, adjusted_price, sizes, photo_ids, client_message_id=None, client_chat_id=None, client_topic_name=None, forward_from_message_id=None, watermarked_photo_ids=None, buyer_message_ids=None):

        try:

            original_price = float(price) / (1 + int(float(adjusted_price.strip('%'))) / 100) if adjusted_price else float(price)

            buyer_message_ids_str = ','.join(map(str, buyer_message_ids)) if buyer_message_ids else None

            self.cursor.execute(

                "INSERT INTO posts (bot_name, message_id, brand, price, original_price, adjusted_price, sizes, photo_ids, client_message_id, client_chat_id, client_topic_name, forward_from_message_id, watermarked_photo_ids, buyer_message_ids) "

                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",

                (bot_name, message_id, brand, float(price), original_price, adjusted_price, sizes, photo_ids, client_message_id, client_chat_id, client_topic_name, forward_from_message_id, watermarked_photo_ids, buyer_message_ids_str)

            )

            self.conn.commit()

        except mysql.connector.Error as e:

            print(f"Error logging post: {e}")

            self.conn.rollback()



    def get_existing_posts(self, brand, photo_ids, price=None, forward_from_message_id=None):

        photo_ids_str = ','.join(photo_ids)

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

                (brand, photo_ids_str, photo_ids_str, float(price), float(price))

            )

        else:

            self.cursor.execute(

                "SELECT client_message_id, client_chat_id, client_topic_name, adjusted_price, sizes "

                "FROM posts WHERE brand = %s AND (photo_ids = %s OR watermarked_photo_ids = %s) AND client_message_id IS NOT NULL "

                "ORDER BY timestamp DESC LIMIT 1",

                (brand, photo_ids_str, photo_ids_str)

            )

        return self.cursor.fetchall()



    def log_pending_photo(self, user_id, message_id, photo_ids, media_group_id=None):

        try:

            valid_photo_ids = [pid for pid in photo_ids if len(pid) > 20 and isinstance(pid, str) and re.match(r'^[A-Za-z0-9_-]+$', pid)]

            if not valid_photo_ids:

                print(f"DEBUG - No valid photo_ids provided: {photo_ids}")

                raise ValueError("No valid photo IDs provided")

            # Remove duplicates

            valid_photo_ids = list(set(valid_photo_ids))

            photo_ids_str = ','.join(valid_photo_ids)

            if media_group_id:

                # Check if exists

                self.cursor.execute(

                    "SELECT id, photo_ids FROM pending_photos WHERE user_id = %s AND media_group_id = %s",

                    (user_id, media_group_id)

                )

                result = self.cursor.fetchone()

                if result:

                    # Update existing

                    existing_id, existing_photo_ids = result

                    existing_ids = existing_photo_ids.split(',')

                    combined_photo_ids = list(set(existing_ids + valid_photo_ids))

                    combined_photo_ids_str = ','.join(combined_photo_ids)

                    self.cursor.execute(

                        "UPDATE pending_photos SET photo_ids = %s, message_id = %s WHERE id = %s",

                        (combined_photo_ids_str, message_id, existing_id)

                    )

                    self.conn.commit()

                    print(f"Debug - Updated pending media group photo: user_id={user_id}, message_id={message_id}, photos={combined_photo_ids_str}, media_group_id={media_group_id}")

                    return

            # Insert new entry

            self.cursor.execute(

                "INSERT INTO pending_photos (user_id, message_id, photo_ids, media_group_id) "

                "VALUES (%s, %s, %s, %s)",

                (user_id, message_id, photo_ids_str, media_group_id)

            )

            self.conn.commit()

            print(f"Debug - Successfully logged pending photo: {photo_ids_str}")

        except mysql.connector.Error as e:

            print(f"DEBUG - Database error logging pending photos: {e}")

            self.conn.rollback()

            raise

        except ValueError as e:

            print(f"DEBUG - Error logging pending photos: {e}")

            raise



    def get_pending_photos(self, user_id, media_group_id=None):

        if media_group_id:

            self.cursor.execute(

                "SELECT message_id, photo_ids, media_group_id FROM pending_photos WHERE user_id = %s AND media_group_id = %s",

                (user_id, media_group_id)

            )

        else:

            self.cursor.execute(

                "SELECT message_id, photo_ids, media_group_id FROM pending_photos WHERE user_id = %s",

                (user_id,)

            )

        return self.cursor.fetchall()



    def clear_pending_photos(self, user_id):

        try:

            self.cursor.execute(

                "DELETE FROM pending_photos WHERE user_id = %s",

                (user_id,)

            )

            self.conn.commit()

        except mysql.connector.Error as e:

            print(f"DEBUG - Error clearing pending_photos: {e}")

            self.conn.rollback()



    def queue_post(self, user_id, photo_ids, description, message_id):

        try:

            self.cursor.execute(

                "INSERT INTO post_queue (user_id, photo_ids, description, message_id, status) "

                "VALUES (%s, %s, %s, %s, %s)",

                (user_id, photo_ids, description, message_id, 'pending')

            )

            self.conn.commit()

        except mysql.connector.Error as e:

            print(f"Error queuing post: {e}")

            self.conn.rollback()

            raise



    def check_queue_duplicate(self, user_id, photo_ids, description):

        self.cursor.execute(

            "SELECT id FROM post_queue WHERE user_id = %s AND photo_ids = %s AND description = %s",

            (user_id, photo_ids, description)

        )

        return self.cursor.fetchone()



    def get_next_queued_post(self):

        self.cursor.execute(

            "SELECT id, user_id, photo_ids, description, message_id FROM post_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1"

        )

        return self.cursor.fetchone()



    def update_queue_status(self, post_id, status):

        try:

            self.cursor.execute(

                "UPDATE post_queue SET status = %s WHERE id = %s",

                (status, post_id)

            )

            self.conn.commit()

        except mysql.connector.Error as e:

            print(f"Error updating queue status: {e}")

            self.conn.rollback()



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

    def log_forwarded_post(self, user_id, bot_name, message_id, brand, photo_ids, caption, forward_from_message_id, client_message_id):
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



    def close(self):
        try:
            self.cursor.close()
            self.conn.close()
        except mysql.connector.Error as e:
            print(f"Error closing database: {e}")