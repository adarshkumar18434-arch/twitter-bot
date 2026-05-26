import os
import sys
import asyncio
import aiohttp

# Fix Windows console encoding so emojis don't crash the script in the terminal
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from bot1 import (
    client, 
    upload_image_to_api, 
    send_to_api, 
    build_post, 
    post_to_linkedin, 
    TARGET_CHANNEL
)

async def run_manual_post():
    # Define a high-quality real-world job posting with correct schema types
    job = {
        "title": "Associate Software Engineer",
        "company": "Accenture",
        "location": "Bangalore, India",
        "applyLink": "https://www.accenture.com/in-en/careers/jobdetails?id=ASE2025",
        "type": "Full-Time",
        "experience": "0-1 Years",
        "education": "B.E / B.Tech / MCA / M.Sc",
        "shortSummary": "Accenture is hiring Associate Software Engineers in Bangalore. Ideal for freshers looking to build their careers in software engineering.",
        "htmlDescription": "<p>Accenture is looking for Associate Software Engineers to join their high-performing software engineering teams in Bangalore. You will design, build, and test applications across various platforms.</p>",
        "jobDescription": "<p>Accenture is looking for Associate Software Engineers to join their high-performing software engineering teams in Bangalore. You will design, build, and test applications across various platforms.</p>",
        "responsibilities": [
            "Collaborate on development and engineering tasks",
            "Write clean, readable, and maintainable code",
            "Support quality testing and applications deployment"
        ],
        "requirements": [
            "Basic programming and scripting knowledge",
            "Analytical thinking and problem-solving abilities",
            "Strong communication and collaborative skills"
        ],
        "skills": ["Python", "Java", "C++", "SQL"],
        "batch": "2024 / 2025 / 2026",
        "salary": "₹4.5 LPA - ₹6.5 LPA",
        "lastDate": None,
        "aboutCompany": "Accenture is a leading global professional services company providing a range of services in strategy, consulting, digital, technology, and operations.",
        "whyJoin": "Accenture offers exceptional learning resources, professional growth pathways, global exposure, and a collaborative environment for freshers.",
        "howToApply": "Click the apply link to submit your application directly on the Accenture careers page.",
        "finalThoughts": "This is a high-demand entry-level position. Be sure to apply today!"
    }
    
    # Calculate slug matching the format
    from slugify import slugify
    import hashlib
    job["slug"] = slugify(job["title"]) + "-" + hashlib.md5(job["shortSummary"].encode()).hexdigest()[:5]

    image_path = r"C:\Users\Adarsh Sharma\.gemini\antigravity\brain\a55d9248-6f74-4ecd-8249-646f0f741abf\accenture_hiring_1779603634909.png"
    
    print("🚀 Starting manual job post process...")
    print(f"Job: {job['title']} at {job['company']}")
    
    # 1. Start Telethon Client
    await client.start()
    print("⚡ Telegram Client started successfully.")
    
    async with aiohttp.ClientSession() as session:
        # 2. Image Upload
        print("📸 Uploading image to persistent storage...")
        uploaded_url = await upload_image_to_api(session, image_path)
        if not uploaded_url:
            print("❌ Image upload failed. Aborting manual post.")
            return
        
        job["image"] = uploaded_url
        print(f"✔ Image uploaded successfully: {uploaded_url}")
        
        # 3. Web Portal Post
        print("🌐 Posting job to website API...")
        response = await send_to_api(session, job)
        print(f"🌐 Website API response: {response}")
        
        slug = job["slug"]
        if isinstance(response, dict):
            backend_slug = (
                response.get("slug")
                or (response.get("data") or {}).get("slug")
                or (response.get("job") or {}).get("slug")
            )
            if backend_slug: 
                slug = backend_slug
                print(f"✔ Using backend slug: {slug}")
        
        # 4. Telegram Post (WITH IMAGE LINK PREVIEW AT THE TOP)
        print("📢 Posting to Telegram channel as a unified message with image preview at the TOP...")
        post = build_post(job, slug)
        try:
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
            print("✔ Successfully posted to Telegram in a single unified message with the image at the TOP!")
        except Exception as e:
            print(f"❌ Telegram posting failed: {e}")
            
        # 5. LinkedIn Post
        print("🔗 Posting to LinkedIn...")
        try:
            await post_to_linkedin(session, job, slug)
            print("✔ Successfully posted to LinkedIn!")
        except Exception as e:
            print(f"❌ LinkedIn posting failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_manual_post())
