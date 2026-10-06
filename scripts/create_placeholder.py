from PIL import Image, ImageDraw, ImageFont
import os

def create_placeholder():
    base_dir = "static/images"
    os.makedirs(base_dir, exist_ok=True)
    
    # 800x800
    img = Image.new('RGB', (800, 800), color=(240, 240, 240))
    d = ImageDraw.Draw(img)
    # Simple text
    d.text((350, 400), "No Image", fill=(150, 150, 150))
    img.save(os.path.join(base_dir, "placeholder.webp"), "WEBP")
    print("Created placeholder.webp")

    # 150x150
    thumb = Image.new('RGB', (150, 150), color=(240, 240, 240))
    d_thumb = ImageDraw.Draw(thumb)
    d_thumb.text((45, 70), "No Image", fill=(150, 150, 150))
    thumb.save(os.path.join(base_dir, "thumb_placeholder.webp"), "WEBP")
    print("Created thumb_placeholder.webp")

if __name__ == "__main__":
    create_placeholder()
