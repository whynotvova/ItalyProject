import re
import io
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from aiogram.types import BufferedInputFile


async def download_photo(file_id, bot):
    file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            return await response.read()


async def add_watermark(image_data, watermark_text):
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
    combined.convert("RGB").save(output, format="JPEG")
    return output.getvalue()


def adjust_price(description):
    print(f"Debug - Adjusting price for description: {description}")
    price_match = re.search(r'(\d+\.?\d*)?\$', description)
    if not price_match:
        print("Debug - No price found")
        return None, None

    original_price = float(price_match.group(1))
    print(f"Debug - Original price: {original_price}$")
    percentage_match = re.search(r'([-+]\d+)%', description)
    if percentage_match:
        percentage = int(percentage_match.group(1))
        print(f"Debug - Percentage: {percentage}%")
        if percentage < 0:
            adjusted_percentage = percentage + 10
            adjusted_price = round(original_price + (original_price * abs(adjusted_percentage) / 100))
            print(f"Debug - Adjusted: {adjusted_percentage}%, Price: {adjusted_price}$")
            return adjusted_price, f"{adjusted_percentage}%"
        else:
            adjusted_price = round(original_price * (1 + percentage / 100))
            print(f"Debug - Adjusted: {adjusted_price}$, Price: {percentage}%")
            return adjusted_price, f"{percentage}%"
    print("Debug - No percentage, using original")
    return original_price, None


def extract_sizes(description):
    size_pattern = r'\b(XS|S|M|L|XL|XXL)\b'
    sizes = re.findall(size_pattern, description, re.IGNORECASE)
    return ' '.join(sizes) if sizes else None


def select_unique_photos(photos):
    """Select the highest-resolution photo for each unique photo ID."""
    if not photos:
        return []
    # Group photos by their base ID (ignoring resolution variants)
    photo_groups = {}
    for photo in photos:
        if hasattr(photo, 'file_id'):
            base_id = photo.file_id[:50]  # Use first 50 chars to group variants
            if base_id not in photo_groups or photo.file_size > photo_groups[base_id].file_size:
                photo_groups[base_id] = photo
    return [photo.file_id for photo in photo_groups.values()]