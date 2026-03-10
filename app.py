import io
import os
import asyncio
import httpx
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

# ------------------- CORS ------------------- #
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------- CONFIG ------------------- #
INFO_API_URL = "https://info-canze1.vercel.app/player-info"
ICON_API_URL = "https://item-info-neon.vercel.app/icon?item_id="
FONT_FILE = "NotoSans-Bold.ttf"

client = httpx.AsyncClient(
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=10.0,
    follow_redirects=True
)

process_pool = ThreadPoolExecutor(max_workers=4)

# ------------------- UTILS ------------------- #
def load_unicode_font(size):
    try:
        font_path = os.path.join(os.path.dirname(__file__), FONT_FILE)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
        return ImageFont.load_default()
    except:
        return ImageFont.load_default()


async def fetch_image_bytes(item_id):
    if not item_id or str(item_id) == "0":
        return None
    try:
        url = f"{ICON_API_URL}{item_id}"
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.content
    except:
        pass
    return None


def bytes_to_image(img_bytes):
    if img_bytes:
        return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    return Image.new('RGBA', (100, 100), (0, 0, 0, 0))


# ------------------- IMAGE PROCESS ------------------- #
def process_banner_image(data, avatar_bytes, banner_bytes, pin_bytes):
    avatar_img = bytes_to_image(avatar_bytes)
    banner_img = bytes_to_image(banner_bytes)
    pin_img = bytes_to_image(pin_bytes)

    level = str(data.get("AccountLevel", "0"))
    name = data.get("AccountName", "Unknown")
    guild = data.get("GuildName", "")

    TARGET_HEIGHT = 400
    avatar_img = avatar_img.resize((TARGET_HEIGHT, TARGET_HEIGHT), Image.LANCZOS)

    # Banner resize and crop
    b_w, b_h = banner_img.size
    if b_w > 50 and b_h > 50:
        banner_img = banner_img.rotate(3, resample=Image.BICUBIC, expand=True)
        b_w, b_h = banner_img.size
        crop_top, crop_bottom, crop_sides = 0.23, 0.32, 0.17
        left = b_w * crop_sides
        top = b_h * crop_top
        right = b_w * (1 - crop_sides)
        bottom = b_h * (1 - crop_bottom)
        banner_img = banner_img.crop((left, top, right, bottom))

    b_w, b_h = banner_img.size
    if b_h > 0:
        new_banner_w = int(TARGET_HEIGHT * (b_w / b_h) * 2.0)
        banner_img = banner_img.resize((new_banner_w, TARGET_HEIGHT), Image.LANCZOS)
    else:
        banner_img = Image.new("RGBA", (800, 400), (50, 50, 50))
        new_banner_w = 400

    # Combined image
    final_w = TARGET_HEIGHT + new_banner_w
    final_h = TARGET_HEIGHT
    combined = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
    combined.paste(avatar_img, (0, 0))
    combined.paste(banner_img, (TARGET_HEIGHT, 0))

    draw = ImageDraw.Draw(combined)
    font_large = load_unicode_font(125)
    font_small = load_unicode_font(95)
    font_level = load_unicode_font(50)

    # Text drawing with stroke
    text_x = TARGET_HEIGHT + 40
    stroke_col, text_col = "black", "white"
    def draw_text_with_stroke(x, y, text, font, size):
        for dx in range(-size, size + 1):
            for dy in range(-size, size + 1):
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_col)
        draw.text((x, y), text, font=font, fill=text_col)

    draw_text_with_stroke(text_x + 25, 40, name, font_large, 4)
    draw_text_with_stroke(text_x + 25, 240, guild, font_small, 3)

    # Pin
    if pin_img and pin_img.size != (100, 100):
        pin_size = 130
        pin_img = pin_img.resize((pin_size, pin_size), Image.LANCZOS)
        combined.paste(pin_img, (0, TARGET_HEIGHT - pin_size), pin_img)

    # Level box
    level_txt = f"Lvl.{level}"
    try:
        bbox = draw.textbbox((0, 0), level_txt, font=font_level)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except:
        text_w, text_h = len(level_txt) * 20, 40
    px, py = 25, 16
    box_x = final_w - (text_w + px * 2)
    box_y = final_h - (text_h + py * 2)
    draw.rectangle([box_x, box_y, final_w, final_h], fill="black")
    draw.text((box_x + px, box_y + py - 6), level_txt, font=font_level, fill="white")

    output = io.BytesIO()
    combined.save(output, format="PNG")
    output.seek(0)
    return output.read()


# ------------------- API ROUTES ------------------- #
@app.get("/player-banner")
async def player_banner(uid: str, region: str):
    if not uid:
        raise HTTPException(status_code=400, detail="UID required")

    try:
        resp = await client.get(INFO_API_URL, params={"uid": uid, "region": region})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Info API error")

    avatar_id = data.get("EquippedAvatar")
    banner_id = data.get("EquippedBanner")
    pin_id = data.get("EquippedPin")

    avatar_bytes, banner_bytes, pin_bytes = await asyncio.gather(
        fetch_image_bytes(avatar_id),
        fetch_image_bytes(banner_id),
        fetch_image_bytes(pin_id)
    )

    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        process_pool,
        process_banner_image,
        data, avatar_bytes, banner_bytes, pin_bytes
    )

    return Response(
        content=img_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )


@app.get("/")
async def home():
    return {
        "message": "NOT found",
        "Your Info Api": INFO_API_URL,
        "Api Endpoint": "/player-banner?uid={uid}&region={region}"
    }


# ------------------- SHUTDOWN ------------------- #
@app.on_event("shutdown")
async def shutdown_event():
    await client.aclose()
    process_pool.shutdown()


# ------------------- RUN ------------------- #
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
