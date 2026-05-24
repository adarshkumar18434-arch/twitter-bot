import asyncio
import os
import sys

# Force UTF-8 stdout
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import bot1
# Monkey-patch API_URL to point to local server for verification testing
bot1.API_URL = "http://localhost:4000/api/jobs"

from bot1 import (
    client,
    process_and_post_job
)

async def main():
    # Define a mock job structure with a non-existent image path to trigger fallback generation
    job_data = {
        "job": {
            "title": "React Frontend Developer Intern (Remote)",
            "company": "Centizen",
            "location": "Remote / India",
            "applyLink": "https://centizen.com/jobs/apply-react-intern",
            "type": "Internship",
            "experience": "Fresher",
            "education": "Any Graduate",
            "salary": "₹15,000 - ₹20,000 / Month",
            "batch": "2025 / 2026",
            "slug": "react-frontend-developer-intern-remote-test",
            "jobDescription": "<p>Centizen is looking for a React Frontend Developer Intern to join their team to build beautiful interfaces.</p>"
        },
        "image_path": "non_existent_image_path_to_trigger_fallback.jpg",
        "hash": "test_hash_fallback_gen_123"
    }

    print("🚀 Starting automated fallback poster scheduler test...")
    print(f"Mock Job: '{job_data['job']['title']}' at '{job_data['job']['company']}'")
    print(f"Provided Image Path: '{job_data['image_path']}' (Should trigger Pillow fallback poster generation!)")
    print(f"Local Mock API URL: '{bot1.API_URL}'")

    print("\n⚡ Starting Telegram client...")
    await client.start()

    try:
        # Run process_and_post_job which will trigger fallback and upload
        await process_and_post_job(job_data)
        print("🎉 Verification test completed successfully!")
    except Exception as e:
        print(f"❌ Error during verification test: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
