# LLM Interface & Gemini API Capabilities Analysis

## Current State Analysis

### ✅ **What EXISTS Currently:**

1. **Web Interface for LLM Interaction**
   - **React UI**: `http://localhost:3000` or `http://localhost:5173` (Vite dev server)
   - **FastAPI Backend**: `http://localhost:8000`
   - **API Endpoint**: `POST /tasks` accepts text input and processes it through Gemini
   - **Chat Interface**: The UI has a chat interface where you can type text and get LLM responses

2. **Current LLM Integration**
   - Uses `ChatGoogleGenerativeAI` from LangChain
   - Model: `gemini-2.0-flash` (configurable via `GEMINI_MODEL`)
   - Text-only input currently supported
   - Tasks are queued via Redis and processed by workers

3. **TaskRequest Structure** (from `shail/core/types.py`)
   ```python
   class TaskRequest(BaseModel):
       text: str  # Primary instruction
       mode: Optional[str]  # auto|code|bio|robo|plasma|research
       attachments: Optional[List[Attachment]]  # Base64 encoded attachments
   ```
   - **Attachments are supported** but not fully integrated with Gemini multimodal API yet

4. **Screen Capture Service** (EXISTS but not integrated with Gemini)
   - **Location**: `native/mac/CaptureService/` (Swift/Xcode)
   - **WebSocket**: `ws://localhost:8765/capture`
   - **Capabilities**: 30-60 FPS screen capture, JPEG compression
   - **Status**: ✅ Built and running, but frames are NOT sent to Gemini yet

---

## ❌ **What's MISSING:**

### 1. **Direct Text-to-LLM Interface**
   - **Current**: Text goes through task queue → worker → agent → Gemini
   - **Missing**: Simple direct chat endpoint that processes text immediately and returns response
   - **What's needed**: A synchronous endpoint like `POST /chat` that:
     - Accepts text input
     - Calls Gemini directly
     - Returns response immediately (no queue, no task tracking)

### 2. **Multimodal Input Support**
   - **Images**: TaskRequest supports attachments, but Gemini multimodal API not integrated
   - **Audio/Voice**: No voice message processing to Gemini
   - **Video**: No video processing
   - **Screen Capture**: CaptureService exists but frames not routed to Gemini

---

## 📋 **What's Needed to Add Direct LLM Chat Interface**

### Option 1: Simple Chat Endpoint (Recommended)
```python
# In apps/shail/main.py
@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Direct chat endpoint - processes text immediately with Gemini.
    No queue, no task tracking, just LLM response.
    """
    settings = get_settings()
    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.7
    )
    
    response = await llm.ainvoke(request.text)
    return ChatResponse(text=response.content)
```

**Required Changes:**
1. Add `ChatRequest` and `ChatResponse` models
2. Add `/chat` endpoint to FastAPI
3. Update UI to use `/chat` for simple conversations
4. Keep `/tasks` for complex multi-step operations

### Option 2: WebSocket Chat (Real-time)
- WebSocket server for streaming responses
- More complex but better UX for long responses

---

## 🎯 **Gemini API Multimodal Capabilities**

Based on Google Gemini API documentation, here's what you CAN route:

### ✅ **Images** - FULLY SUPPORTED
- **Formats**: PNG, JPEG, WEBP, HEIC, HEIF
- **How to send**: Base64 encoded in message content
- **Example**:
  ```python
  from langchain_google_genai import ChatGoogleGenerativeAI
  from langchain_core.messages import HumanMessage
  
  llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
  
  message = HumanMessage(
      content=[
          {"type": "text", "text": "What's in this image?"},
          {
              "type": "image_url",
              "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}
          }
      ]
  )
  response = llm.invoke([message])
  ```

### ✅ **Videos** - SUPPORTED
- **Formats**: MP4, MPEG, MOV, AVI, FLV, WEBM, WMV, 3GPP
- **How to send**: File upload or base64 encoded
- **Note**: Gemini processes video frames, not full video stream

### ✅ **Audio** - SUPPORTED
- **Formats**: WAV, MP3, AIFF, AAC, OGG, FLAC
- **How to send**: Base64 encoded audio data
- **Use case**: Voice messages, audio transcription

### ✅ **Screen Recordings** - POSSIBLE
- **How**: Convert screen recordings to MP4/MOV
- **Integration**: CaptureService → Save frames as video → Send to Gemini
- **Current**: CaptureService captures frames but doesn't create videos

### ✅ **Voice Messages** - POSSIBLE
- **How**: Record audio → Convert to WAV/MP3 → Send to Gemini
- **Current**: LiveKit agent exists but uses Google Realtime API, not Gemini

### ❓ **Xcode Capture Services (Xtools)**
- **Status**: Not explicitly documented
- **Workaround**: If Xtools outputs images/videos, convert to supported formats
- **Integration**: CaptureService (Swift) could be extended to use Xtools

---

## 🛠️ **Implementation Roadmap**

### Phase 1: Direct Chat Interface (Simple)
**Files to modify:**
1. `apps/shail/main.py` - Add `/chat` endpoint
2. `shail/core/types.py` - Add `ChatRequest` and `ChatResponse`
3. `apps/shail-ui/src/services/api.js` - Add `chat()` function
4. `apps/shail-ui/src/components/ChatInput.jsx` - Add direct chat option

**Time estimate**: 1-2 hours

### Phase 2: Image Support
**Files to modify:**
1. `apps/shail/main.py` - Update `/chat` to handle images
2. `shail/agents/code.py` - Add multimodal message support
3. `apps/shail-ui/src/components/ChatInput.jsx` - Add image upload
4. Update `TaskRequest` processing to use multimodal API

**Time estimate**: 2-3 hours

### Phase 3: Audio/Voice Support
**Files to modify:**
1. Add audio recording in UI
2. Convert audio to base64
3. Send to Gemini with audio content type
4. Handle audio responses (text-to-speech optional)

**Time estimate**: 3-4 hours

### Phase 4: Screen Capture Integration
**Files to modify:**
1. `services/vision/service.py` - Connect to CaptureService WebSocket
2. Convert frames to video or send as image sequence
3. Route to Gemini with screen context
4. Add real-time screen analysis capability

**Time estimate**: 4-6 hours

### Phase 5: Video Processing
**Files to modify:**
1. Add video upload support
2. Process video frames or send full video
3. Integrate with Gemini video understanding API

**Time estimate**: 2-3 hours

---

## 📝 **Quick Implementation: Direct Chat Endpoint**

Here's the minimal code to add a direct chat interface:

### 1. Add to `shail/core/types.py`:
```python
class ChatRequest(BaseModel):
    text: str
    attachments: Optional[List[Attachment]] = None

class ChatResponse(BaseModel):
    text: str
    model: str = "gemini-2.0-flash"
```

### 2. Add to `apps/shail/main.py`:
```python
from shail.core.types import ChatRequest, ChatResponse
from langchain_google_genai import ChatGoogleGenerativeAI

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Direct chat endpoint - immediate LLM response."""
    settings = get_settings()
    
    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    
    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.7
    )
    
    # Build message content
    content = [{"type": "text", "text": request.text}]
    
    # Add images if provided
    if request.attachments:
        for att in request.attachments:
            if att.mime_type and att.mime_type.startswith("image/"):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{att.mime_type};base64,{att.content_b64}"
                    }
                })
    
    from langchain_core.messages import HumanMessage
    message = HumanMessage(content=content)
    
    response = await llm.ainvoke([message])
    
    return ChatResponse(
        text=response.content,
        model=settings.gemini_model
    )
```

### 3. Update UI (`apps/shail-ui/src/services/api.js`):
```javascript
export async function chat(text, attachments = []) {
  const response = await api.post('/chat', {
    text,
    attachments
  });
  return response.data;
}
```

---

## 🎤 **Voice Messages - Current State**

You have a **LiveKit agent** setup in:
- `shail/agent.py`
- Uses `google.beta.realtime.RealtimeModel` (NOT Gemini API)
- This is for real-time voice conversations, not text-to-Gemini

**To add voice-to-Gemini:**
1. Record audio in browser (Web Audio API)
2. Convert to WAV/MP3
3. Send base64 audio to Gemini via multimodal API
4. Get text response
5. Optionally: Text-to-speech for audio response

---

## 📸 **Screen Capture - Current State**

**What exists:**
- ✅ `native/mac/CaptureService/` - Swift service capturing screen at 30 FPS
- ✅ WebSocket server on `ws://localhost:8765/capture`
- ✅ JPEG frames being broadcast

**What's missing:**
- ❌ Integration with Gemini API
- ❌ Frame-to-video conversion
- ❌ Real-time screen analysis

**To integrate:**
1. Connect Python service to CaptureService WebSocket
2. Collect frames (e.g., 1 second = 30 frames)
3. Option A: Send as image sequence to Gemini
4. Option B: Convert to MP4 video → Send to Gemini
5. Get analysis response

---

## 🔑 **Summary**

### ✅ **You CAN do:**
1. **Text to LLM**: Already works via `/tasks` endpoint
2. **Direct chat**: Needs simple `/chat` endpoint (easy to add)
3. **Images**: Gemini supports it, just need to wire it up
4. **Audio**: Gemini supports it, need audio recording + base64 encoding
5. **Videos**: Gemini supports it, need video upload/processing
6. **Screen recordings**: Possible via CaptureService → video conversion

### ❌ **Current limitations:**
1. No direct synchronous chat (only async task queue)
2. Multimodal inputs not wired to Gemini API yet
3. Screen capture not connected to Gemini
4. Voice messages not using Gemini (using Realtime API instead)

### 🚀 **Quick wins:**
1. Add `/chat` endpoint (1-2 hours) - gives you direct LLM interaction
2. Add image upload to chat (2-3 hours) - enables image analysis
3. Connect CaptureService to Gemini (4-6 hours) - enables screen analysis

---

## 📚 **References**

- Gemini API Docs: https://ai.google.dev/gemini-api/docs
- LangChain Gemini: `langchain_google_genai.ChatGoogleGenerativeAI`
- Current API: `apps/shail/main.py`
- Current UI: `apps/shail-ui/src/`
- CaptureService: `native/mac/CaptureService/`

