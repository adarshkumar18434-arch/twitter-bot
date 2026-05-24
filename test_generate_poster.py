import os
import urllib.request
from PIL import Image, ImageDraw, ImageFont

# Define font settings
FONT_DIR = "fonts"
os.makedirs(FONT_DIR, exist_ok=True)
FONT_PATH = os.path.join(FONT_DIR, "Roboto-Bold.ttf")
FONT_URL = "https://raw.githubusercontent.com/googlefonts/roboto/master/src/hinted/Roboto-Bold.ttf"

# Download font if not present
if not os.path.exists(FONT_PATH):
    print("Downloading Roboto-Bold font from googlefonts/roboto on GitHub...")
    try:
        req = urllib.request.Request(
            FONT_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req) as response, open(FONT_PATH, 'wb') as out_file:
            out_file.write(response.read())
        print("Font downloaded successfully!")
    except Exception as e:
        print(f"Error downloading font: {e}")

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        # Get width of test line
        w = font.getbbox(test_line)[2]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def generate_poster(title, company, location, salary, output_path):
    width, height = 1200, 630
    
    # Create a beautiful gradient background
    base_grad = Image.new("RGB", (2, 2))
    base_grad.putpixel((0, 0), (15, 23, 42))  # Slate 900
    base_grad.putpixel((1, 0), (30, 41, 59))  # Slate 800
    base_grad.putpixel((0, 1), (15, 25, 45))  # Navy
    base_grad.putpixel((1, 1), (43, 20, 85))  # Deep Indigo/Purple
    
    img = base_grad.resize((width, height), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    try:
        font_logo = ImageFont.truetype(FONT_PATH, 28)
        font_company = ImageFont.truetype(FONT_PATH, 34)
        font_title = ImageFont.truetype(FONT_PATH, 54)
        font_meta = ImageFont.truetype(FONT_PATH, 24)
        font_btn = ImageFont.truetype(FONT_PATH, 26)
    except Exception as e:
        print(f"Error loading font, using default: {e}")
        font_logo = font_company = font_title = font_meta = font_btn = ImageFont.load_default()
        
    # Draw branding logo top-left
    draw.text((80, 50), "NEXTJOBPOST.COM", fill=(56, 189, 248), font=font_logo)
    
    # Draw top horizontal decorative line
    draw.line([(80, 95), (200, 95)], fill=(56, 189, 248), width=3)
    
    # Draw "WE ARE HIRING" / Company header
    draw.text((80, 140), f"WE ARE HIRING AT {company.upper()}", fill=(244, 63, 94), font=font_company)
    
    # Draw Job Title (with wrapping)
    wrapped_title = wrap_text(title, font_title, 1040)
    y_offset = 210
    for line in wrapped_title:
        draw.text((80, y_offset), line, fill=(255, 255, 255), font=font_title)
        y_offset += 75
        
    # Draw Meta details
    meta_y = y_offset + 30
    meta_text = []
    if location:
        meta_text.append(f"Location: {location}")
    if salary:
        meta_text.append(f"Salary: {salary}")
    
    if meta_text:
        draw.text((80, meta_y), "  |  ".join(meta_text), fill=(209, 213, 219), font=font_meta)
        
    # Draw Button at the bottom
    btn_x0, btn_y0 = 80, 500
    btn_x1, btn_y1 = 280, 560
    draw.rounded_rectangle([(btn_x0, btn_y0), (btn_x1, btn_y1)], radius=12, fill=(239, 68, 68))
    
    btn_txt = "Apply Now"
    btn_txt_w = font_btn.getbbox(btn_txt)[2] - font_btn.getbbox(btn_txt)[0]
    btn_txt_h = font_btn.getbbox(btn_txt)[3] - font_btn.getbbox(btn_txt)[1]
    
    btn_txt_x = btn_x0 + (btn_x1 - btn_x0 - btn_txt_w) // 2
    btn_txt_y = btn_y0 + (btn_y1 - btn_y0 - btn_txt_h) // 2 - 3
    
    draw.text((btn_txt_x, btn_txt_y), btn_txt, fill=(255, 255, 255), font=font_btn)
    
    # Save Image
    img.save(output_path, "PNG")
    print(f"Poster generated successfully at: {output_path}")

# Run a test generation
generate_poster(
    title="Associate Software Engineer (Java, React) - 2026 Batch",
    company="Centizen",
    location="Chennai / Bangalore (Remote)",
    salary="₹4.5 LPA - ₹6.5 LPA",
    output_path=r"C:\Users\Adarsh Sharma\.gemini\antigravity\brain\a55d9248-6f74-4ecd-8249-646f0f741abf\test_poster.png"
)
