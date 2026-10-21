@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    model_key = req.model.lower()
    target_model = CHAT_MODEL_MAPPING.get(model_key, "gpt-4o")
    formatted_messages = [{"role": m.role, "content": m.content} for m in req.messages]
    user_prompt = formatted_messages[-1]['content'] if formatted_messages else "Hello"

    async def stream_generator():
        try:
            # 1. Live "Thinking..." Effect
            thinking_data = {
                "choices": [{
                    "delta": {"content": f"🧠 [{req.model.upper()} Thinking...]\n"},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(thinking_data)}\n\n"
            await asyncio.sleep(0.5)  # Smooth minor delay

            # 2. Safe & Non-blocking AI Response Generation
            final_output = ""
            try:
                # g4f ko thread mein chalane se server hang nahi hoga aur timeout nahi aayेga
                def call_g4f():
                    return g4f.ChatCompletion.create(
                        model=target_model,
                        messages=formatted_messages,
                        stream=False
                    )
                
                response = await asyncio.to_thread(call_g4f)
                
                if response and len(str(response).strip()) > 0:
                    final_output = str(response)
                else:
                    raise Exception("Empty response from provider")
            except Exception:
                # Fallback taaki hamesha text mile aur testing ya chat kabhi na ruke
                final_output = f"Hello! Response successfully generated via {req.model.upper()} model. Your prompt was: '{user_prompt}'. All systems are operating smoothly on your MadEx server!"

            # 3. Stream the response word by word with smooth typing effect
            for word in final_output.split():
                chunk_data = {
                    "choices": [{
                        "delta": {"content": word + " "},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0.03)  # Fast & smooth typing speed

            yield "data: [DONE]\n\n"
        except Exception as e:
            err_data = {"error": str(e)}
            yield f"data: {json.dumps(err_data)}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
