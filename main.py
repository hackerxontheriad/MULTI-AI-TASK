from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import json
import asyncio

app = FastAPI(title="MadEx Playwright AI Server", version="7.0")

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_id: str
    model: str
    messages: List[Message]
    stream: Optional[bool] = True

@app.get("/")
def home():
    return {"status": "online", "message": "MadEx Playwright AI Server is active!"}

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    # Streaming generator jo timeout nahi hone dega aur live chunks bhejega
    async def event_generator():
        try:
            # Pehle "Thinking..." ya connection status ka chunk bhej sakte hain
            thinking_data = {
                "choices": [{
                    "delta": {"content": "🧠 [Thinking...]\n"},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(thinking_data)}\n\n"
            await asyncio.sleep(0.5)

            # Aapka purana Playwright / automation logic yahan execute hoga
            # Simulation / Actual response chunking:
            simulated_response = f"Hello! Processing your request using {req.model} via Playwright engine. Here is your answer: "
            
            for word in simulated_response.split():
                chunk_data = {
                    "choices": [{
                        "delta": {"content": word + " "},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0.1)

            yield "data: [DONE]\n\n"
        except Exception as e:
            err_data = {"error": str(e)}
            yield f"data: {json.dumps(err_data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
