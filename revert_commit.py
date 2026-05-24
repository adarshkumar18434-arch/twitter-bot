import subprocess

job_repo_path = r"e:\job\job"

print("=== Reverting bad commit from next-job repo ===")

# Temporarily point job portal to next-job to revert the bad commit
subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/adarshkumar18434-arch/next-job.git"], cwd=job_repo_path, shell=True)

# Fetch latest from next-job
subprocess.run(["git", "fetch", "origin"], cwd=job_repo_path, shell=True)

# Reset to parent commit (24e08e8) — this removes the bad Cloudinary commit
result = subprocess.run(["git", "reset", "--hard", "24e08e8"], cwd=job_repo_path, shell=True, capture_output=True, text=True)
print(result.stdout)
print(result.stderr)

# Force push — this deletes the bad commit from GitHub
result2 = subprocess.run(["git", "push", "--force", "origin", "main"], cwd=job_repo_path, shell=True, capture_output=True, text=True)
print(result2.stdout)
print(result2.stderr)

# Restore job portal remote back to the correct repo
subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/adarsh200201/job.git"], cwd=job_repo_path, shell=True)

# Also restore the local job portal code back to its latest state
subprocess.run(["git", "reset", "--hard", "HEAD@{1}"], cwd=job_repo_path, shell=True)

result3 = subprocess.run(["git", "remote", "get-url", "origin"], cwd=job_repo_path, shell=True, capture_output=True, text=True)
print(f"\nJob portal remote restored to: {result3.stdout.strip()}")
print("Done!")
