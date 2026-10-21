import requests

API_BASE = "https://madex-api-chatai.onrender.com"  # Ya aapka local http://127.0.0.1:8000

# 1. Test Chat & Code Generation (e.g., DeepSeek or ChatGPT for coding)
chat_payload = {
    "user_id": "test_developer_1",
    "model": "deepseek",  # Aap "chatgpt", "claude", etc. bhi try kar sakte hain
    "messages": [
        {"role": "system", "content": "You are an expert Python developer."},
        {"role": "user", "content": "Write a quick Python function to check if a number is prime."}
    ]
}

print("[*] Testing Chat & Code Generation...")
res = requests.post(f"{API_BASE}/v1/chat/completions", json=chat_payload)
print(res.json())

print("\n--------------------------------------------------\n")

# 2. Test Video Generation (Google Veo / Video Flow)
video_payload = {
    "user_id": "test_developer_1",
    "prompt": "Cinematic shot of a futuristic neon city in rain, 4k",
    "aspect_ratio": "16:9"
}

print("[*] Testing Video Generation...")
video_res = requests.post(f"{API_BASE}/v1/video/generate", json=video_payload)
print(video_res.json())
