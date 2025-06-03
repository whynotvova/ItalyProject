import re
import io
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from aiogram.types import BufferedInputFile

async def download_photo(file_id, bot):
    try:
        file = await bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    print(f"Debug - Failed to download photo: file_id={file_id}, status={response.status}")
                    return None
    except Exception as e:
        print(f"Debug - Error downloading photo: file_id={file_id}, error={e}")
        return None

async def add_watermark(image_data, watermark_text):
    try:
        image = Image.open(io.BytesIO(image_data)).convert("RGBA")
        txt = Image.new("RGBA", image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt)
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        width, height = image.size
        x = width - text_width - 10
        y = height - text_height - 10
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 128))
        combined = Image.alpha_composite(image, txt)
        output = io.BytesIO()
        combined.convert('RGB').save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"Debug - Error adding watermark: {e}")
        return image_data

def adjust_price(description):
    print(f"Debug - Adjusting price for description: {description}")
    price_match = re.search(r'(\d+\.?\d*)\s*([€$])', description)
    if not price_match:
        print("Debug - No price found in description")
        return None, None, '€'  # Default to € if no currency found
    original_price = float(price_match.group(1))
    currency = price_match.group(2)
    print(f"Debug - Original price: {original_price} {currency}")
    percentage_match = re.search(r'([-+]\d+)%', description)
    if percentage_match:
        percentage = int(percentage_match.group(1))
        print(f"Debug - Percentage: {percentage}%")
        if percentage < 0:
            adjusted_percentage = percentage + 10
            adjusted_price = round(original_price + (original_price * abs(adjusted_percentage) / 100))
            print(f"Debug - Adjusted percentage: {adjusted_percentage}%, Price: {adjusted_price} {currency}")
            return adjusted_price, f"{adjusted_percentage}%", currency
        else:
            adjusted_price = round(original_price + (original_price * abs(percentage) / 100))
            print(f"Debug - Adjusted: {adjusted_price} {currency}, Percentage: {percentage}%")
            return adjusted_price, f"{percentage}%", currency
    print("Debug - No percentage, using original price")
    return original_price, None, currency

def extract_sizes(description):
    letter_size_pattern = r'\b(X{0,3}(?:XS|S|M|L|XL|XXL|XXXL))\b'
    numeric_size_pattern = r'\b(\d{1,2}(?:\.\d)?(?:-\d{1,2}(?:\.\d)?)?)\b'
    letter_sizes = re.findall(letter_size_pattern, description, re.IGNORECASE)
    numeric_sizes = re.findall(numeric_size_pattern, description)
    sizes = [s for s in letter_sizes + numeric_sizes if not re.match(r'^-?\d+%$', s)]
    return ' '.join(sorted(sizes)) if sizes else None

def select_unique_photos(photos):
    if not photos:
        return []
    photo_groups = {}
    for photo in photos:
        if hasattr(photo, 'file_id') and photo.file_id:
            base_id = photo.file_id[:50]
            if base_id not in photo_groups or (hasattr(photo, 'file_size') and photo.file_size and photo.file_size > (photo_groups[base_id].file_size or 0)):
                photo_groups[base_id] = photo
    return [photo.file_id for photo in photo_groups.values()]