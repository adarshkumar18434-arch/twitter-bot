import os
import re
import asyncio
import hashlib
import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from slugify import slugify

# =========================
# ENV
# =========================
load_dotenv(override=True)

API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
API_TOKEN = os.getenv("API_TOKEN")
API_KEY   = os.getenv("API_KEY")

# LinkedIn Credentials (from get_linkedin_token.py)
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN   = os.getenv("LINKEDIN_PERSON_URN", "")  # e.g. urn:li:person:XXXXX

SOURCE_CHANNELS = [
    "me",
    # ── Off-Campus & Tech (Freshers) ──
    "CSEOfficialTelegram",
    "goyalarsh",
    "IT_Jobs_Career",
    "CSE_IT_BCA_MCA_Computer_Jobs",
    "placementkit",
    "placementdriveofficial",
    "fresher_offcampus_drives",
    "walkindrive",
    "freshershunt",
    "fresherearth",

    # ── Internships & College Students ──
    "jobs_and_internships_updates",
    "InternshipsIndia",
    "FresherInternships",
    "PaidInternshipsIndia",
    "StartupInternships",

    # ── Remote & WFH ──
    "seekeras",
    "seekeraswfh",
    "joblii",
    "RemoteJobsGlobal",
    "RemoteWorkDaily",

    # ── Specialized Tech Roles ──
    "PythonDeveloperJobs",
    "JavaScriptFullStack",
    "QA_Testing_Jobs",

    # ── General & Sarkari Naukri ──
    "Government_Jobs_Sarkari_Naukri",
    "SarkariResultOfficialChannel",
    "FreeJobAlertOfficial"
]

TARGET_CHANNEL = "nextjobpost"

API_URL = os.getenv("API_URL", "https://next-job-cfbh.onrender.com/api/jobs")
SITE_BASE_URL = "https://nextjobpost.in"

# ── Queue Setup ──
QUEUE_FILE = "job_queue.json"
# Default 30 minutes (1800 seconds) between posts
POST_INTERVAL = int(os.getenv("POST_INTERVAL", 1800))
PENDING_IMAGES_DIR = "pending_images"

if not os.path.exists(PENDING_IMAGES_DIR):
    os.makedirs(PENDING_IMAGES_DIR)

# ── Telegram Setup ──
SESSION_DATA = os.getenv("TELEGRAM_SESSION_STRING", "session")
# If it looks like a string session (long), use StringSession, otherwise use file name
session = StringSession(SESSION_DATA) if len(SESSION_DATA) > 25 else SESSION_DATA
client = TelegramClient(session, API_ID, API_HASH)

# =========================
# MEMORY CACHE (persistent)
# =========================
CACHE_FILE = "posted_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        combined_path = None
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_cache(cache_set):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(cache_set)[-500:], f)

# ── Queue Functions ──
def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_queue(queue):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)

seen = load_cache()

def hash_text(t):
    return hashlib.md5(t.encode()).hexdigest()

# =========================
# FILTER
# =========================
JOB_WORDS = ["job", "hiring", "apply", "vacancy", "intern", "opening", "recruitment", "role", "drive"]
JOB_EMOJIS = ["🔔", "🚀", "📍", "💼", "🎓", "⏳", "👉"]

def normalize_text(text):
    # Very basic normalization for common bold/italic unicode characters
    # This is a bit complex to do perfectly without a library, but we can do a broad check
    # Many telegram bots use Mathematical Bold characters.
    # Alternatively, we can just check for emojis or 'http' presence.
    return text.lower()

def is_job(text):
    if not text: return False
    t = text.lower()
    
    # Check for direct word matches in lowercase
    has_job_word = any(w in t for w in JOB_WORDS)
    
    # Check for emojis often used in job posts
    has_job_emoji = any(e in text for e in JOB_EMOJIS)
    
    # Check for links (crucial for jobs)
    has_link = "http" in t or "bit.ly" in t or "t.me" in t
    
    # If it has a job word (even normalized) or a job emoji, and it has a link, it's likely a job
    # We also check for 'role' or 'hiring' in the original text to catch unicode bold 
    # (since 'hiring' in script might still contain searchable fragments or we match emoji)
    
    # Fallback for unicode bold: if it looks like a job post structure
    looks_like_job = any(indicator in text for indicator in ["𝗝𝗼𝗯", "𝗛𝗶𝗿𝗶𝗻𝗴", "𝗥𝗼𝗹𝗲", "𝗔𝗽𝗽𝗹𝘆"])
    
    return (has_job_word or has_job_emoji or looks_like_job) and has_link

from google import genai
from google.genai import types
import json

client_gemini = genai.Client(api_key=API_KEY) if API_KEY else None

# =========================
# EXTRACTOR (AI + Basic Fallback)
# =========================
def extract_basic(text):
    """Fallback parser if Gemini fails or is not setup"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0][:120] if lines else "Job Opening"
    urls = re.findall(r'https?://[^\s]+', text)
    apply_link = urls[0] if urls else ""

    company = "Not Mentioned"
    location = "Not Mentioned"
    job_type = "Full-Time"

    for l in lines:
        if "company" in l.lower():
            company = l.split(":")[-1].strip()
        if "location" in l.lower():
            location = l.split(":")[-1].strip()
        if "intern" in l.lower():
            job_type = "Internship"

    return {
        "title": title,
        "company": company,
        "location": location,
        "applyLink": apply_link,
        "jobDescription": text,
        "type": job_type,
        "experience": "Fresher / 0-2 Years",
        "education": "Graduation",
        "slug": slugify(title) + "-" + hashlib.md5(text.encode()).hexdigest()[:5]
    }

from urllib.parse import urlparse

def clean_company_name(s):
    words_orig = s.split()
    s_lower = " " + s.lower() + " "
    
    # Remove common phrases and job titles
    patterns_to_remove = [
        r"\boff\s*campus\b", r"\bcampus\b", r"\bdrive\b", r"\bhiring\b", r"\brecruitment\b", 
        r"\bjobs?\b", r"\bcareers?\b", r"\bnew\b", r"\bfreshers?\b", 
        r"\binternships?\b", r"\binterns?\b", r"\b202[0-9]\b", r"\bapply\s*now\b",
        r"\bopportunity\b", r"\bopenings?\b", r"\balerts?\b", r"\bupdates?\b",
        r"\bsoftware\s*engineer\b", r"\bsoftware\s*developer\b", r"\bdeveloper\b",
        r"\bengineer\b", r"\banalyst\b", r"\btester\b", r"\bsupport\b", r"\bconsultant\b",
        r"\bassociate\b", r"\bexecutive\b", r"\btrainee\b", r"\bmanager\b",
        r"\bfor\b", r"\bat\b", r"\bthe\b", r"\ban\b", r"\ba\b", r"\bin\b", r"\bto\b", r"\bof\b", r"\bwith\b"
    ]
    
    cleaned = s_lower
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, " ", cleaned)
    
    cleaned = cleaned.strip(" -|:_!@#%^&*()[]{}<>.,/\\\"'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    result_words = []
    for w in cleaned.split():
        orig_match = None
        for orig_w in words_orig:
            clean_orig = re.sub(r"[^a-zA-Z0-9]", "", orig_w)
            if clean_orig.lower() == w.lower():
                orig_match = clean_orig
                break
        if orig_match and orig_match.isupper() and len(orig_match) >= 2:
            result_words.append(orig_match)
        else:
            result_words.append(w.capitalize())
            
    return " ".join(result_words)

def get_company_from_link(url):
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        parts = netloc.split(".")
        if len(parts) >= 2:
            generic_domains = {"com", "org", "net", "in", "co", "io", "us", "uk", "edu", "gov", "me", "info", "tech"}
            generic_hosts = {"forms", "gle", "github", "notion", "linktr", "t", "telegram", "facebook", "twitter", "linkedin", "instagram", "youtube", "drive", "docs"}
            domain_parts = [p for p in parts if p not in generic_domains]
            if domain_parts:
                main_domain = domain_parts[-1]
                if main_domain not in generic_hosts:
                    return main_domain.upper() if len(main_domain) <= 3 else main_domain.capitalize()
    except:
        pass
    return None

def guess_company_from_title(title):
    if not title:
        return None
    
    # 1. Try pattern "... at [Company]" or "... by [Company]"
    at_match = re.search(r"\b(?:at|by)\s+([a-zA-Z0-9\s]+)", title, re.IGNORECASE)
    if at_match:
        candidate_words = at_match.group(1).strip().split()
        if candidate_words:
            candidate = " ".join(candidate_words[:2])
            cleaned = clean_company_name(candidate)
            if cleaned and cleaned.lower() not in ["new", "hiring", "apply", "urgent", "huge", "latest", "alert", "job", "software", "associate", "junior", "senior", "lead"]:
                return cleaned
                
    # 2. Try splitting by common delimiters
    delimiters = ["|", "-", ":", "–"]
    for delim in delimiters:
        if delim in title:
            parts = title.split(delim)
            for part in parts:
                cleaned = clean_company_name(part)
                if cleaned and len(cleaned.split()) <= 3 and len(cleaned) < 25:
                    if cleaned.lower() not in ["new hiring", "hiring", "apply now", "freshers", "for", "software", "associate", "junior", "senior", "lead"]:
                        return cleaned

    # 3. Try first word
    words = title.split()
    if words:
        first_word_cleaned = clean_company_name(words[0])
        if first_word_cleaned and len(first_word_cleaned) >= 2:
            if first_word_cleaned.lower() not in ["new", "hiring", "apply", "urgent", "huge", "latest", "alert", "job", "software", "associate", "junior", "senior", "lead"]:
                return first_word_cleaned
                
    # 4. Fallback to clean whole title
    cleaned = clean_company_name(title)
    if cleaned and len(cleaned.split()) <= 3 and len(cleaned) < 25:
        if cleaned.lower() not in ["new hiring", "hiring", "apply now", "freshers", "for", "software", "associate", "junior", "senior", "lead"]:
            return cleaned
            
    return None

def is_valid_job(job):
    """
    Validates the job details. If any required information is missing, not specified, 
    not disclosed, or not mentioned, we fill in a default or guess to ensure we do not skip.
    """
    # Auto-default salary and batch if missing or containing forbidden placeholders
    forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
    
    # 1. Auto-default salary
    salary = job.get("salary")
    if not salary or any(term in str(salary).lower() for term in forbidden_terms):
        job["salary"] = "Best in Industry"
        
    # 2. Auto-default batch
    batch = job.get("batch")
    if not batch or any(term in str(batch).lower() for term in forbidden_terms):
        job["batch"] = "2024 / 2025 / 2026"
        
    # 3. Auto-default company (guess from title or URL first, then fallback to Top Company)
    company = job.get("company")
    if not company or any(term in str(company).lower() for term in forbidden_terms):
        guessed = guess_company_from_title(job.get("title"))
        if not guessed:
            guessed = get_company_from_link(job.get("applyLink"))
        job["company"] = guessed or "Top Company"
        
    # 4. Auto-default location
    location = job.get("location")
    if not location or any(term in str(location).lower() for term in forbidden_terms):
        job["location"] = "Pan India"
        
    # 5. Auto-default experience
    experience = job.get("experience")
    if not experience or any(term in str(experience).lower() for term in forbidden_terms):
        job["experience"] = "Fresher / 0-2 Years"
        
    # 6. Auto-default education
    education = job.get("education")
    if not education or any(term in str(education).lower() for term in forbidden_terms):
        job["education"] = "Any Graduate"
        
    # Key fields to check
    check_keys = ["company", "location", "salary", "experience", "education", "batch"]
    
    for key in check_keys:
        val = job.get(key)
        if not val:
            return False, f"Missing required field: {key}"
        
        val_lower = str(val).strip().lower()
        if any(term in val_lower for term in forbidden_terms):
            return False, f"Placeholder/Missing value '{val}' detected in field: {key}"
            
    return True, ""

async def extract_with_ai(text):
    """Uses modern Gemini 2.5 Flash to extract job fields"""
    if not API_KEY or not client_gemini:
        print("💡 API_KEY (Gemini) not found in .env, using basic parser...")
        return extract_basic(text)

    prompt = f"""
Analyze this Telegram job posting and extract the details.
Return ONLY a valid, raw JSON object (no markdown formatting, no `json` blocks) with the following exact keys:
"title", "company", "location", "applyLink", "type", "experience", "education", "shortSummary", "htmlDescription", "responsibilities", "requirements", "skills", "batch", "salary", "lastDate", "aboutCompany", "whyJoin", "howToApply", "finalThoughts".

Rules:
1. DO NOT guess, fabricate, or generate any details that are not explicitly present in the job posting text.
2. If any of the following fields are not clearly and explicitly specified in the text, you MUST set their value exactly to "Not Mentioned":
   - "company" (Do NOT guess from the apply link domain, do NOT use "Hiring Company" or "Confidential")
   - "location" (Do NOT default to "Pan India" or "Remote")
   - "salary"
   - "experience"
   - "education"
   - "batch"
3. 'type' MUST be one of: "Full-Time", "Part-Time", "Internship", "Contract", "Remote", "Hybrid".
4. 'applyLink' must be the first http/https link found.
5. 'shortSummary' MUST be a clean, professional 15-20 word summary of the role. NO emojis.
6. 'htmlDescription' MUST be beautifully formatted HTML based on the provided text. Use <h2>, <ul>, <li>, <br/> and <strong> tags.
7. 'responsibilities' MUST be a JSON array of strings detailing the job role. If none, return [].
8. 'requirements' MUST be a JSON array of strings detailing eligibility. If none, return [].
9. 'skills' MUST be a JSON array of strings. If none, return [].
10. 'lastDate' MUST be either an empty string "" or a valid date string if a deadline is mentioned.
11. 'aboutCompany' MUST be a detailed 3-4 sentence professional context about the extracted company. Generate this intelligently only if the company name is actually present, otherwise set to "".
12. 'whyJoin' MUST be a persuasive 3-4 sentence paragraph highlighting the benefits of working at this company for this role.
13. 'howToApply' MUST be clear, step-by-step instructions detailing the application process for the candidate.
14. 'finalThoughts' MUST be a short, encouraging concluding mark wishing the applicant success.

Job Posting Text:
{text}
"""
    try:
        response = await client_gemini.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        
        # Sanitize response just in case Gemini hallucinates markdown blocks
        clean_json = response.text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:-3].strip()
            
        data = json.loads(clean_json)
        # 🎨 Give the beautiful HTML text to the job detail page, and clean summary to the home page cards
        title_val = data.get("title", "Job Opening")
        data["jobDescription"] = data.get("htmlDescription", text)
        data["description"] = data.get("shortSummary", title_val[:150] + "...")
        data["aboutCompany"] = data.get("aboutCompany", "")
        data["whyJoin"] = data.get("whyJoin", "")
        data["howToApply"] = data.get("howToApply", "")
        data["finalThoughts"] = data.get("finalThoughts", "")
        data["highlightText"] = data.get("title", "Freshers Eligible")
        base_slug = slugify(data.get("title", "Job Opening"))
        unique_id = hashlib.md5(text.encode()).hexdigest()[:5]
        data["slug"] = f"{base_slug}-{unique_id}"
        
        # 🚀 Inject the predefined WhatsApp & Telegram Social links!
        data["whatsapp"] = "https://chat.whatsapp.com/LVpuUJluTpUEdIc4daAemQ"
        data["telegram"] = "https://t.me/nextjobpost"
        
        return data
    except Exception as e:
        print(f"⚠️ AI Parsing failed: {e}. Falling back to basic parser.")
        return extract_basic(text)

# =========================
# STEP 1A → POSTER GENERATOR & UPLOAD WITH RETRY
# =========================
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "fonts"
FONT_PATH = os.path.join(FONT_DIR, "Roboto-Bold.ttf")
FONT_URL = "https://raw.githubusercontent.com/googlefonts/roboto/master/src/hinted/Roboto-Bold.ttf"

async def ensure_font_downloaded():
    """Asynchronously downloads Roboto-Bold font from GitHub/GoogleFonts raw repository."""
    if not os.path.exists(FONT_PATH):
        os.makedirs(FONT_DIR, exist_ok=True)
        print("📥 [POSTER] Downloading Roboto-Bold font from Google Fonts GitHub repository...")
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(FONT_URL, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(FONT_PATH, "wb") as f:
                            f.write(content)
                        print("✅ [POSTER] Font downloaded successfully!")
                    else:
                        print(f"⚠️ [POSTER] Font download failed with status {resp.status}")
        except Exception as e:
            print(f"⚠️ [POSTER] Font download failed: {e}")

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
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
    """Generates a professional 1200x630 job poster dynamically with Pillow."""
    width, height = 1200, 630
    
    # 1. Create a beautiful deep space blue/indigo gradient
    base_grad = Image.new("RGB", (2, 2))
    base_grad.putpixel((0, 0), (15, 23, 42))  # Slate 900
    base_grad.putpixel((1, 0), (30, 41, 59))  # Slate 800
    base_grad.putpixel((0, 1), (15, 25, 45))  # Deep Space Blue
    base_grad.putpixel((1, 1), (43, 20, 85))  # Dark Indigo
    
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
        print(f"⚠️ Error loading font, using default: {e}")
        font_logo = font_company = font_title = font_meta = font_btn = ImageFont.load_default()
        
    # Draw branding logo top-left
    draw.text((80, 50), "NEXTJOBPOST.COM", fill=(56, 189, 248), font=font_logo)
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


def render_text_block(job, width=1200, padding=40):
    """Render the full job text into an image block to append under/alongside a poster.
    Returns a PIL Image object containing the rendered text block."""
    from PIL import ImageFont

    # Prepare fonts
    try:
        font_title = ImageFont.truetype(FONT_PATH, 42)
        font_body = ImageFont.truetype(FONT_PATH, 24)
    except Exception:
        font_title = font_body = ImageFont.load_default()

    # Build the text content
    lines = []
    lines.append(job.get('title', 'Job Opening'))
    lines.append("\n")
    summary = job.get('shortSummary') or job.get('description') or ''
    if summary:
        lines.append(summary)
        lines.append("\n")

    fields = [
        ("Company", job.get('company', 'Top Company')),
        ("Location", job.get('location', 'Pan India')),
        ("Education", job.get('education', 'Any Graduate')),
        ("Experience", job.get('experience', 'Fresher / 0-2 Years')),
        ("Salary", job.get('salary', 'Best in Industry')),
        ("Job Type", job.get('type', 'Full-Time')),
    ]

    for k, v in fields:
        lines.append(f"{k}: {v}")

    # Responsibilities, Requirements, Skills
    if job.get('responsibilities'):
        lines.append('\nResponsibilities:')
        for r in job.get('responsibilities', [])[:6]:
            lines.append(f" - {r}")

    if job.get('requirements'):
        lines.append('\nRequirements:')
        for r in job.get('requirements', [])[:6]:
            lines.append(f" - {r}")

    if job.get('skills'):
        lines.append('\nSkills: ' + ', '.join(job.get('skills', [])[:10]))

    lines.append('\nApply: ' + job.get('applyLink', job.get('image', SITE_BASE_URL)))

    # Convert to single text string and wrap
    text = "\n".join(lines)

    # Create a temporary image to calculate height
    dummy = Image.new('RGB', (width, 10), color=(20, 25, 35))
    draw = ImageDraw.Draw(dummy)

    wrapped_lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            wrapped_lines.append('')
            continue
        # wrap by approximate character width using font metrics
        words = paragraph.split()
        cur = []
        for w in words:
            test = ' '.join(cur + [w])
            wbox = draw.textbbox((0, 0), test, font=font_body)
            if wbox[2] <= (width - 2 * padding):
                cur.append(w)
            else:
                wrapped_lines.append(' '.join(cur))
                cur = [w]
        if cur:
            wrapped_lines.append(' '.join(cur))

    # Estimate height
    line_height = (font_body.getbbox('Ay')[3] - font_body.getbbox('Ay')[1]) + 8
    title_height = (font_title.getbbox('Ay')[3] - font_title.getbbox('Ay')[1]) + 16
    total_height = padding + title_height + len(wrapped_lines) * line_height + padding

    block = Image.new('RGB', (width, max(400, total_height)), color=(18, 24, 36))
    draw = ImageDraw.Draw(block)

    # Draw title
    y = padding
    draw.text((padding, y), job.get('title', 'Job Opening'), fill=(255, 255, 255), font=font_title)
    y += title_height

    # Draw wrapped lines
    for ln in wrapped_lines:
        draw.text((padding, y), ln, fill=(230, 230, 230), font=font_body)
        y += line_height

    return block


def combine_image_with_text(image_path, job, output_path, width=1200):
    """Combine an existing image (photo or poster) with the rendered text block beneath it.
    Saves combined image to output_path and returns the path."""
    try:
        base = Image.open(image_path).convert('RGB')
    except Exception:
        # If cannot open, just render text block as image
        block = render_text_block(job, width=width)
        block.save(output_path, 'PNG')
        return output_path

    # Resize base to target width while keeping aspect
    w_percent = (width / float(base.size[0]))
    new_h = int((float(base.size[1]) * float(w_percent)))
    base_resized = base.resize((width, new_h), Image.Resampling.LANCZOS)

    text_block = render_text_block(job, width=width)

    # Create final combined image
    final_h = base_resized.size[1] + text_block.size[1]
    final = Image.new('RGB', (width, final_h), (18, 24, 36))
    final.paste(base_resized, (0, 0))
    final.paste(text_block, (0, base_resized.size[1]))

    final.save(output_path, 'PNG')
    return output_path

async def upload_image_to_api(session, file_path, retries=3, delay=5):
    """
    Uploads an image to the Render backend.
    Includes cold-start mitigation, timeout/HTML response handling, and 3 retries.
    """
    # 1. Cold start handling: Ping the backend API
    health_url = API_URL.replace("/jobs", "/health")
    print(f"⏳ [UPLOAD] Pinging Render backend ({health_url}) to mitigate cold start...")
    try:
        async with session.get(health_url, timeout=60) as res:
            await res.read()
    except Exception as e:
        print(f"⚠️ [UPLOAD] Backend ping failed (expected if completely cold): {e}")

    # 2. Wait 5 seconds to ensure backend starts up/receives connections
    print("⏳ [UPLOAD] Waiting 5 seconds for Render backend connection readiness...")
    await asyncio.sleep(5)

    headers = {}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"

    upload_url = API_URL.replace("/jobs", "/upload/image")
    
    for attempt in range(1, retries + 1):
        print(f"📸 [UPLOAD] Attempt {attempt}/{retries}: Uploading {os.path.basename(file_path)}...")
        try:
            data = aiohttp.FormData()
            data.add_field('image',
                           open(file_path, 'rb'),
                           filename=os.path.basename(file_path),
                           content_type='image/jpeg')

            async with session.post(upload_url, data=data, headers=headers, timeout=30) as res:
                # Detect 503 Service Unavailable
                if res.status == 503:
                    print(f"⚠️ [UPLOAD] 503 Service Unavailable on attempt {attempt}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Detect HTML response page (Render proxy/routing errors)
                content_type = res.headers.get("Content-Type", "")
                if "text/html" in content_type:
                    print(f"⚠️ [UPLOAD] Received HTML page instead of JSON on attempt {attempt}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Try parsing JSON
                try:
                    resp_data = await res.json()
                except Exception as json_err:
                    print(f"⚠️ [UPLOAD] Invalid JSON output on attempt {attempt}: {json_err}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)
                        continue
                    break

                # Handle success response
                if resp_data.get("success"):
                    img_url_val = resp_data.get('imageUrl', '')
                    if img_url_val.startswith("http://") or img_url_val.startswith("https://"):
                        image_url = img_url_val
                    else:
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(API_URL)
                            base_url = f"{parsed.scheme}://{parsed.netloc}"
                        except Exception:
                            base_url = "https://job-tdg8.onrender.com"
                        image_url = f"{base_url}{img_url_val}"
                    print(f"✅ [UPLOAD] Success! URL: {image_url}")
                    return image_url
                else:
                    print(f"⚠️ [UPLOAD] API returned success=False on attempt {attempt}: {resp_data}")

        except asyncio.TimeoutError:
            print(f"⚠️ [UPLOAD] Request timed out on attempt {attempt}")
        except FileNotFoundError:
            print(f"❌ [UPLOAD] File not found: {file_path}")
            break
        except Exception as e:
            print(f"⚠️ [UPLOAD] Unexpected error on attempt {attempt}: {e}")

        if attempt < retries:
            wait_time = delay * attempt
            print(f"⏳ [UPLOAD] Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)

    print("❌ [UPLOAD] Failed to upload image after all retries.")
    return ""

# =========================
# STEP 1B → SEND TO API FIRST
# =========================
async def send_to_api(session, job):
    headers = {
        "Content-Type": "application/json"
    }
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
        
    async with session.post(API_URL, json=job, headers=headers) as res:
        try:
            data = await res.json()
            return data
        except:
            return None

def build_post(job, slug):
    """Build a rich, fully-featured Telegram post with maximum engagement."""
    job_url    = f"{SITE_BASE_URL}/{slug}"
    title      = job.get('title', 'Job Opening')
    company    = job.get('company', 'Top Company')
    location   = job.get('location', 'Pan India')
    education  = job.get('education', 'Any Graduate')
    experience = job.get('experience', 'Fresher / 0-2 Years')
    salary     = job.get('salary', 'Best in Industry')
    batch      = job.get('batch', '2024 / 2025 / 2026')
    job_type   = job.get('type', 'Full-Time')
    last_date  = job.get('lastDate', '')
    summary    = job.get('shortSummary', '') or job.get('description', '')
    why_join   = job.get('whyJoin', '')
    how_apply  = job.get('howToApply', '')
    final_note = job.get('finalThoughts', '')

    # ── Skills (up to 6) ──
    skills_raw = job.get('skills', [])
    skills_section = ''
    if skills_raw:
        skill_list = '  •  '.join(skills_raw[:6])
        skills_section = f"\n🛠 **Skills:** {skill_list}\n"

    # ── Responsibilities (up to 3) ──
    resp_raw = job.get('responsibilities', [])
    resp_section = ''
    if resp_raw:
        bullets = '\n'.join(f'   ▸ {r}' for r in resp_raw[:3])
        resp_section = f"\n📋 **What You'll Do:**\n{bullets}\n"

    # ── Requirements (up to 3) ──
    req_raw = job.get('requirements', [])
    req_section = ''
    if req_raw:
        bullets = '\n'.join(f'   ✔ {r}' for r in req_raw[:3])
        req_section = f"\n✅ **Requirements:**\n{bullets}\n"

    # ── Why Join ──
    why_section = ''
    if why_join:
        # Trim to 180 chars for Telegram readability
        trimmed = why_join[:180].rstrip()
        why_section = f"\n💡 **Why Join?**\n{trimmed}...\n"

    # ── How to Apply ──
    how_section = ''
    if how_apply:
        trimmed = how_apply[:200].rstrip()
        how_section = f"\n📝 **How to Apply:**\n{trimmed}\n"

    # ── Optional fields ──
    batch_line    = f"🎯 **Batch:**      {batch}\n" if batch else ''
    type_line     = f"💼 **Job Type:**   {job_type}\n"
    deadline_line = f"⏰ **Last Date:**  {last_date}\n" if last_date else ''
    summary_line  = f"\n📣 {summary}\n" if summary else ''

    # ── Final thoughts ──
    final_section = ''
    if final_note:
        final_section = f"\n✨ {final_note}\n"

    return (
        f"🔥 **{title}** 🔥\n"
        f"🏢 **{company}**\n"
        f"{summary_line}"
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Location:**   {location}\n"
        f"🎓 **Education:**  {education}\n"
        f"⏳ **Experience:** {experience}\n"
        f"💰 **Salary:**     {salary}\n"
        f"{type_line}"
        f"{batch_line}"
        f"{deadline_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
        f"{skills_section}"
        f"{resp_section}"
        f"{req_section}"
        f"{why_section}"
        f"{how_section}"
        f"{final_section}"
        f"\n🔗 **Apply Here →** {job_url}\n"
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 **Next Job Post** — Your daily job alert hub\n"
        f"🌐 More Jobs:  https://nextjobpost.in\n"
        f"💼 LinkedIn:   https://www.linkedin.com/in/next-job-post-199b5b371\n"
        f"👉 **Join Channel:** https://t.me/nextjobpost\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 **Share with friends who need a job!** 👇"
    )

def build_post_caption(job, slug):
    """Build a compact Telegram image caption (max ~1000 chars to stay within limit)."""
    job_url    = f"{SITE_BASE_URL}/{slug}"
    title      = job.get('title', 'Job Opening')
    company    = job.get('company', 'Top Company')
    location   = job.get('location', 'Pan India')
    salary     = job.get('salary', 'Best in Industry')
    
    # Build a compact caption
    caption = (
        f"🔥 {title}\n"
        f"🏢 {company}\n"
        f"📍 {location} | 💰 {salary}\n"
        f"\n🔗 Apply: {job_url}\n"
        f"👉 Join: https://t.me/nextjobpost"
    )
    
    # Ensure caption doesn't exceed Telegram's 1024 char limit for media
    if len(caption) > 1024:
        # Truncate title and company if needed
        caption = (
            f"🔥 {title[:80]}\n"
            f"🏢 {company[:50]}\n"
            f"📍 {location[:40]} | 💰 {salary[:40]}\n"
            f"\n🔗 Apply: {job_url}\n"
            f"👉 Join: https://t.me/nextjobpost"
        )
    
    return caption

# =========================
# STEP 2B → POST TO LINKEDIN (Rich + Image)
# =========================
def build_linkedin_post(job, slug):
    """Build a rich, fully-detailed LinkedIn post optimised for reach and engagement."""
    job_url      = f"{SITE_BASE_URL}/{slug}"
    title        = job.get('title', 'Job Opening')
    company      = job.get('company', 'Top Company')
    location     = job.get('location', 'Pan India')
    education    = job.get('education', 'Any Graduate')
    experience   = job.get('experience', 'Fresher / 0-2 Years')
    salary       = job.get('salary', 'As per industry standards')
    batch        = job.get('batch', '')
    job_type     = job.get('type', 'Full-Time')
    last_date    = job.get('lastDate', '')
    summary      = job.get('shortSummary', '') or job.get('description', '')
    about_co     = job.get('aboutCompany', '')
    why_join     = job.get('whyJoin', '')
    how_apply    = job.get('howToApply', '')
    final_note   = job.get('finalThoughts', '')

    # ── Attention-grabbing opening hook ─────────────────────────────────
    if 'intern' in job_type.lower() or 'intern' in title.lower():
        hook = f"🎓 Freshers & Students — This is YOUR moment! {company} is hiring!\n"
    elif 'remote' in location.lower() or 'remote' in job_type.lower():
        hook = f"🏠 Work from Anywhere! {company} has a Remote opening for you!\n"
    else:
        hook = f"🚀 Exciting Career Opportunity at {company}!\n"

    # ── About Company (2-3 sentences) ───────────────────────────────────
    about_section = ''
    if about_co:
        about_section = f"\n🏢 About {company}:\n{about_co}\n"

    # ── Skills bullet points (up to 6) ──────────────────────────────────
    skills_raw = job.get('skills', [])
    skills_section = ''
    if skills_raw:
        skill_bullets = '\n'.join(f'   ▸ {s}' for s in skills_raw[:6])
        skills_section = f'\n🛠️ Key Skills Required:\n{skill_bullets}\n'

    # ── Key responsibilities (up to 5) ──────────────────────────────────
    resp_raw = job.get('responsibilities', [])
    resp_section = ''
    if resp_raw:
        resp_bullets = '\n'.join(f'   📌 {r}' for r in resp_raw[:5])
        resp_section = f'\n📋 What You Will Do:\n{resp_bullets}\n'

    # ── Requirements (up to 5) ──────────────────────────────────────────
    req_raw = job.get('requirements', [])
    req_section = ''
    if req_raw:
        req_bullets = '\n'.join(f'   ✔ {r}' for r in req_raw[:5])
        req_section = f'\n✅ Who Should Apply:\n{req_bullets}\n'

    # ── Why Join section ────────────────────────────────────────────────
    why_section = ''
    if why_join:
        why_section = f'\n💡 Why Join {company}?\n{why_join}\n'

    # ── How to Apply ────────────────────────────────────────────────────
    how_section = ''
    if how_apply:
        how_section = f'\n📝 How to Apply:\n{how_apply}\n'

    # ── Optional badge lines ─────────────────────────────────────────────
    batch_line    = f"🎯 Batch        : {batch}\n" if batch and batch.lower() not in ('not mentioned', 'not specified', '') else ''
    deadline_line = f"⏰ Last Date    : {last_date}  ← Don't miss the deadline!\n" if last_date else ''
    type_badge    = f"💼 Job Type     : {job_type}\n"

    # ── Final encouraging note ───────────────────────────────────────────
    final_section = ''
    if final_note:
        final_section = f'\n✨ {final_note}\n'
    else:
        final_section = '\n✨ Best of luck with your application! You\'ve got this! 💪\n'

    # ── Smart dynamic hashtags ───────────────────────────────────────────
    hashtag_set = {
        '#Hiring', '#Jobs', '#JobAlert', '#NextJobPost', '#Career',
        '#JobSearch', '#Recruitment', '#OpenToWork',
    }
    if 'intern' in job_type.lower() or 'intern' in title.lower():
        hashtag_set.update(['#Internship', '#InternshipAlert', '#Fresher', '#CampusHiring'])
    else:
        hashtag_set.update(['#Fresher', '#JobOpening', '#NowHiring', '#OffCampus'])
    if any(t in title.lower() for t in ['software', 'developer', 'engineer', 'tech', 'data', 'python', 'java', 'devops', 'cloud']):
        hashtag_set.update(['#TechJobs', '#SoftwareJobs', '#ITJobs', '#TechHiring'])
    if 'remote' in location.lower() or 'remote' in job_type.lower():
        hashtag_set.update(['#RemoteJobs', '#WorkFromHome', '#RemoteWork'])
    if 'finance' in title.lower() or 'banking' in title.lower():
        hashtag_set.update(['#FinanceJobs', '#BankingJobs', '#BFSI'])
    if 'data' in title.lower() or 'analyst' in title.lower():
        hashtag_set.update(['#DataScience', '#Analytics', '#DataJobs'])
    hashtags = ' '.join(sorted(hashtag_set))

    post_text = (
        f"{hook}\n"
        f"🔥 {title}\n"
        f"📣 {summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Location     : {location}\n"
        f"🎓 Education    : {education}\n"
        f"⏳ Experience   : {experience}\n"
        f"💰 Salary       : {salary}\n"
        f"{type_badge}"
        f"{batch_line}"
        f"{deadline_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
        f"{about_section}"
        f"{resp_section}"
        f"{req_section}"
        f"{skills_section}"
        f"{why_section}"
        f"{how_section}"
        f"{final_section}"
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 Apply Now → {job_url}\n\n"
        f"📊 Follow NextJobPost for daily fresh opportunities!\n"
        f"📢 Telegram: https://t.me/nextjobpost\n"
        f"🌐 Website:  https://nextjobpost.in\n"
        f"\n👍 Like  |  🔁 Repost  |  💬 Tag someone who needs this!\n\n"
        f"{hashtags}"
    )
    return post_text


async def _upload_image_to_linkedin(session, image_url: str) -> str:
    """
    Downloads the job image and uploads it to LinkedIn.
    Returns the LinkedIn asset URN string, or "" on failure.
    """
    headers_auth = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # Step A: Register the upload
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": LINKEDIN_PERSON_URN,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }
            ]
        }
    }
    try:
        async with session.post(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            json=register_payload,
            headers=headers_auth
        ) as reg_resp:
            if reg_resp.status not in (200, 201):
                txt = await reg_resp.text()
                print(f"⚠️  LinkedIn image register failed [{reg_resp.status}]: {txt[:200]}")
                return ""
            reg_data = await reg_resp.json()
    except Exception as e:
        print(f"❌ LinkedIn image register error: {e}")
        return ""

    upload_url = (
        reg_data.get("value", {})
                .get("uploadMechanism", {})
                .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
                .get("uploadUrl", "")
    )
    asset_urn = reg_data.get("value", {}).get("asset", "")

    if not upload_url or not asset_urn:
        print("⚠️  LinkedIn: could not parse uploadUrl or asset URN from register response.")
        return ""

    # Step B: Download the image bytes
    try:
        async with session.get(image_url) as img_resp:
            if img_resp.status != 200:
                print(f"⚠️  Could not download job image [{img_resp.status}]: {image_url}")
                return ""
            image_bytes = await img_resp.read()
    except Exception as e:
        print(f"❌ Image download error: {e}")
        return ""

    # Step C: Upload binary to LinkedIn's CDN
    try:
        async with session.put(
            upload_url,
            data=image_bytes,
            headers={
                "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
                "Content-Type": "image/jpeg"
            }
        ) as put_resp:
            if put_resp.status not in (200, 201):
                txt = await put_resp.text()
                print(f"⚠️  LinkedIn image PUT failed [{put_resp.status}]: {txt[:200]}")
                return ""
            print(f"📸 LinkedIn image uploaded: {asset_urn}")
            return asset_urn
    except Exception as e:
        print(f"❌ LinkedIn image PUT error: {e}")
        return ""


async def post_to_linkedin(session, job, slug):
    """Post a rich job card to LinkedIn (with image if available)."""
    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        print("⚠️  LinkedIn credentials missing in .env — skipping LinkedIn post.")
        return False

    post_text = build_linkedin_post(job, slug)

    # Strictly check that the generated LinkedIn post does not contain any forbidden/placeholder terms
    forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
    if any(term in post_text.lower() for term in forbidden_terms):
        print(f"🚫 [ABORT] Generated LinkedIn post contains placeholder terms. Skipping LinkedIn post.")
        return False
    job_url   = f"{SITE_BASE_URL}/{slug}"

    headers = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # ── Try to attach image ──────────────────────────────────────────────────
    image_url = job.get("image", "")
    asset_urn = ""
    if image_url:
        print(f"📸 Uploading image to LinkedIn: {image_url}")
        asset_urn = await _upload_image_to_linkedin(session, image_url)

    # ── Build payload (image post vs article link) ───────────────────────────
    if asset_urn:
        # Rich IMAGE post — higher reach than plain article links
        media_block = [
            {
                "status": "READY",
                "media": asset_urn,
                "title": {"text": job.get('title', 'Job Opening')[:400]},
                "description": {"text": job.get('shortSummary', '')[:256]}
            }
        ]
        media_category = "IMAGE"
    else:
        # Fallback: article / link preview
        media_block = [
            {
                "status": "READY",
                "originalUrl": job_url,
                "title": {"text": job.get('title', 'Job Opening')[:400]},
                "description": {"text": job.get('shortSummary', '')[:256]}
            }
        ]
        media_category = "ARTICLE"

    payload = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": media_category,
                "media": media_block
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    try:
        async with session.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers=headers
        ) as resp:
            if resp.status in (200, 201):
                data    = await resp.json()
                post_id = data.get('id', 'unknown')
                mode    = "with image 📸" if asset_urn else "with article link 🔗"
                print(f"✅ LinkedIn Posted {mode}! Post ID: {post_id}")
                return True
            else:
                text = await resp.text()
                print(f"⚠️  LinkedIn post failed [{resp.status}]: {text[:400]}")
                return False
    except Exception as e:
        print(f"❌ LinkedIn post error: {e}")
        return False


# =========================
# HANDLER
# =========================
async def process_and_post_job(job_data):
    """The master function that actually builds the posts and sends them out."""
    job = job_data["job"]
    image_path = job_data.get("image_path")
    h = job_data.get("hash")

    print(f"\n🚀 [SCHEDULER] Processing job: {job['title']}")

    # Double check that the job contains all real information and no placeholder/missing values
    is_valid, reason = is_valid_job(job)
    if not is_valid:
        print(f"🚫 [ABORT] Job '{job['title']}' has invalid or missing details: {reason}. Aborting social posts.")
        return

    async with aiohttp.ClientSession() as session:
        # 1. Image Upload
        uploaded_url = None
        has_real_image = image_path and os.path.exists(image_path) and os.path.getsize(image_path) > 0
        
        if has_real_image:
            uploaded_url = await upload_image_to_api(session, image_path)
            
        if not uploaded_url:
            print(f"⚠️ [SCHEDULER] Real image upload failed or image missing for '{job['title']}'. Generating professional fallback poster...")
            fallback_path = os.path.join(PENDING_IMAGES_DIR, f"generated_{h}.png")
            
            try:
                await ensure_font_downloaded()
                generate_poster(
                    title=job.get("title", "Job Opportunity"),
                    company=job.get("company", "Top Company"),
                    location=job.get("location", "Pan India"),
                    salary=job.get("salary", "Best in Industry"),
                    output_path=fallback_path
                )
                print(f"🎨 [SCHEDULER] Fallback poster generated at: {fallback_path}")
                
                # Upload the generated poster
                uploaded_url = await upload_image_to_api(session, fallback_path)
                
                # Update image_path so subsequent steps (Telegram/LinkedIn) post the generated poster
                image_path = fallback_path
            except Exception as gen_err:
                print(f"❌ [SCHEDULER] Fallback poster generation/upload failed: {gen_err}")

        if not uploaded_url:
            print(f"🚫 [ABORT] Failed to upload any valid image for job '{job['title']}'. Aborting social posts.")
            return

        job["image"] = uploaded_url
        print(f"📸 Image bound: {uploaded_url}")

        # 2. Website Post
        response = await send_to_api(session, job)
        print(f"🌐 Website status: {response}")

        if isinstance(response, dict) and response.get("success") is False:
            print(f"⚠️ Website API rejected job. Aborting social posts.")
            return

        # Get final slug
        slug = job["slug"]
        if isinstance(response, dict):
            backend_slug = (
                response.get("slug")
                or (response.get("data") or {}).get("slug")
                or (response.get("job") or {}).get("slug")
            )
            if backend_slug: slug = backend_slug

        # 3. Telegram Post
        post = build_post(job, slug)

        # Strictly check that the generated Telegram post does not contain any forbidden/placeholder terms
        forbidden_terms = ["not mentioned", "not specified", "not disclosed", "confidential", "hiring company"]
        if any(term in post.lower() for term in forbidden_terms):
            print(f"🚫 [ABORT] Generated Telegram post contains placeholder terms. Skipping Telegram post.")
            return

        try:
            # Prepend hidden image link using Markdown to let Telegram pull it as a premium preview banner
            if uploaded_url:
                telegram_post = f"[\u200b]({uploaded_url}){post}"
            else:
                telegram_post = post

            # Use raw SendMessageRequest with invert_media=True to show the image preview at the TOP of the message
            from telethon.tl.functions.messages import SendMessageRequest
            import random

            peer_entity = await client.get_input_entity(TARGET_CHANNEL)
            msg_text, entities = await client._parse_message_text(telegram_post, 'md')

            await client(SendMessageRequest(
                peer=peer_entity,
                message=msg_text,
                entities=entities,
                invert_media=True,
                random_id=random.randint(-2**63, 2**63 - 1)
            ))
            print(f"✔ Telegram Posted in a single unified message section with the image at the TOP.")
        except Exception as e:
            print(f"❌ Telegram failed: {e}")

        # 4. LinkedIn Post
        await post_to_linkedin(session, job, slug)

        # Cleanup image
        try:
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass


async def scheduler_task():
    """Background loop that posts one job every X minutes."""
    print(f"🕒 Scheduler started. Interval: {POST_INTERVAL} seconds.")
    while True:
        queue = load_queue()
        if queue:
            job_data = queue.pop(0) # Oldest first
            save_queue(queue)
            
            try:
                await process_and_post_job(job_data)
            except Exception as e:
                print(f"❌ Scheduler processing error: {e}")
            
            print(f"⏳ Waiting {POST_INTERVAL}s for next slot...")
            await asyncio.sleep(POST_INTERVAL)
        else:
            # Check every 30s if something new arrived in queue
            await asyncio.sleep(30)


async def handler(event):
    text = event.message.message or ""
    if not text: return

    print(f"\n[DEBUG] 📩 Incoming message: {text[:60]}...")
    if not is_job(text): return

    h = hash_text(text)
    if h in seen: return

    # Strictly require a real, non-static/non-fake image attached to the incoming Telegram message.
    is_image_doc = event.message.document and event.message.document.mime_type and event.message.document.mime_type.startswith('image/')
    if not (event.message.photo or is_image_doc):
        print(f"🚫 [SKIPPING] Job '{text[:30]}...' has no image attached. Only jobs with real images are processed.")
        return

    # Parse and extract fields using modern AI
    job = await extract_with_ai(text)
    
    # Verify that all required fields are present and valid (no "Not Mentioned" etc.)
    is_valid, reason = is_valid_job(job)
    if not is_valid:
        print(f"🚫 [SKIPPING] Job '{text[:30]}...' rejected: {reason}")
        return

    # Capture image now (before message disappears)
    image_path = os.path.join(PENDING_IMAGES_DIR, f"{h}.jpg")
    try:
        await event.message.download_media(file=image_path)
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            print(f"🚫 [SKIPPING] Image download failed or file empty for job '{text[:30]}...'.")
            if os.path.exists(image_path):
                try: os.remove(image_path)
                except: pass
            return
    except Exception as e:
        print(f"🚫 [SKIPPING] Error downloading image: {e}")
        return

    # Add to queue
    queue = load_queue()
    queue.append({
        "job": job,
        "image_path": image_path,
        "hash": h,
        "timestamp": time.time()
    })
    save_queue(queue)
    
    # Mark as seen so we don't queue it twice
    seen.add(h)
    save_cache(seen)
    
    print(f"📥 Job Queued! Total in queue: {len(queue)}")


# =========================
# RUN
# =========================
import time
async def main():
    await client.start()
    print("Dual Pipeline Job Agent with Scheduler Running...")
    
    # 🛡️ Validate channels
    valid_channels = []
    for ch in SOURCE_CHANNELS:
        try:
            entity = await client.get_input_entity(ch)
            valid_channels.append(entity)
        except Exception as e:
            print(f"⚠️ Skipping channel '{ch}': {e}")
            
    if not valid_channels:
        print("❌ No valid channels found.")
        return

    client.add_event_handler(handler, events.NewMessage(chats=valid_channels))
    
    print(f"👂 Listening to {len(valid_channels)} channels...")
    
    # Start the scheduler in the background
    asyncio.create_task(scheduler_task())
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())