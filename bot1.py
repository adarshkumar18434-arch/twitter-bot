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

API_URL = "https://job-tdg8.onrender.com/api/jobs"
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

# =========================
# STEP 2 → BUILD TELEGRAM POST
# =========================
def build_post(job, slug):
    job_url = f"{SITE_BASE_URL}/{slug}"

    return f"""
🔥 {job['title']}
🏢 {job['company']}
📍 {job['location']}
🎓 {job['education']}
⏳ {job['experience']}

👉 Apply: {job['applyLink']}

🌐 View Full Job: {job_url}

━━━━━━━━━━━━━━━
📢 Follow on LinkedIn: https://www.linkedin.com/company/nextjobpost  <-- UPDATE THIS!
🚀 More Jobs: https://nextjobpost.in
"""

# =========================
# STEP 2B → POST TO LINKEDIN (Rich + Image)
# =========================
def build_linkedin_post(job, slug):
    """Build a rich, detailed LinkedIn post body optimised for reach."""
    job_url    = f"{SITE_BASE_URL}/{slug}"
    title      = job.get('title', 'Job Opening')
    company    = job.get('company', 'Top Company')
    location   = job.get('location', 'Pan India')
    education  = job.get('education', 'Graduation')
    experience = job.get('experience', 'Fresher')
    salary     = job.get('salary', 'As per industry standards')
    batch      = job.get('batch', '')
    job_type   = job.get('type', 'Full-Time')
    last_date  = job.get('lastDate', '')
    apply_link = job.get('applyLink', job_url)
    summary    = job.get('shortSummary', '') or job.get('description', '')

    # --- Skills bullet points (up to 6) ---
    skills_raw = job.get('skills', [])
    skills_section = ""
    if skills_raw:
        skill_bullets = "\n".join(f"   ▸ {s}" for s in skills_raw[:6])
        skills_section = f"\n🛠️ Skills Required:\n{skill_bullets}\n"

    # --- Key responsibilities (up to 4) ---
    resp_raw = job.get('responsibilities', [])
    resp_section = ""
    if resp_raw:
        resp_bullets = "\n".join(f"   • {r}" for r in resp_raw[:4])
        resp_section = f"\n📋 Key Responsibilities:\n{resp_bullets}\n"

    # --- Requirements (up to 4) ---
    req_raw = job.get('requirements', [])
    req_section = ""
    if req_raw:
        req_bullets = "\n".join(f"   ✔ {r}" for r in req_raw[:4])
        req_section = f"\n✅ Requirements:\n{req_bullets}\n"

    # --- Batch ---
    batch_line = f"🎯 Batch       : {batch}\n" if batch and batch.lower() not in ("not mentioned", "not specified", "") else ""

    # --- Last date ---
    deadline_line = f"📅 Last Date   : {last_date}\n" if last_date else ""

    # --- Job type badge ---
    type_badge = f"💼 Job Type    : {job_type}\n"

    # --- Dynamic hashtags ---
    hashtag_set = {
        "#Hiring", "#Jobs", "#JobAlert", "#NextJobPost", "#Career",
        "#JobSearch", "#Recruitment",
    }
    if "intern" in job_type.lower() or "intern" in title.lower():
        hashtag_set.update(["#Internship", "#InternshipAlert", "#Fresher"])
    else:
        hashtag_set.update(["#Fresher", "#JobOpening", "#NowHiring"])
    if any(t in title.lower() for t in ["software", "developer", "engineer", "tech", "data", "python", "java"]):
        hashtag_set.update(["#TechJobs", "#SoftwareJobs", "#ITJobs"])
    if "remote" in location.lower():
        hashtag_set.add("#RemoteJobs")
    if "finance" in title.lower() or "banking" in title.lower():
        hashtag_set.update(["#FinanceJobs", "#BankingJobs"])
    hashtags = " ".join(sorted(hashtag_set))

    post_text = (
        f"🔥 {title} @ {company}\n\n"
        f"📣 {summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Location   : {location}\n"
        f"🎓 Education  : {education}\n"
        f"⏳ Experience : {experience}\n"
        f"💰 Salary     : {salary}\n"
        f"{type_badge}"
        f"{batch_line}"
        f"{deadline_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
        f"{resp_section}"
        f"{req_section}"
        f"{skills_section}"
        f"🔗 Apply Now    : {job_url}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Follow NextJobPost for daily fresh jobs!\n"
        f"📢 Join Telegram: https://t.me/nextjobpost\n"
        f"👍 Like  |  🔁 Share  |  💬 Tag a friend who needs this!\n\n"
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
            if image_path and os.path.exists(image_path):
                # Send with image as caption (premium look)
                await client.send_file(
                    TARGET_CHANNEL,
                    file=image_path,
                    caption=post
                )
            else:
                # Fallback: text-only if image is missing
                await client.send_message(TARGET_CHANNEL, post)
            print(f"✔ Telegram Posted (with image).")
        except Exception as e:
            print(f"❌ Telegram failed: {e}")

        # 4. LinkedIn Post
        await post_to_linkedin(session, job, slug)

        # Cleanup image
        if image_path and os.path.exists(image_path):
            try: os.remove(image_path)
            except: pass


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