# Vision Service

Screen frame analysis for OCR, object detection, and visual understanding.

## Features

- **OCR**: Extract text from screen frames using Tesseract
- **VLM Integration**: Describe screens using Vision-Language Models (GPT-4V, Claude Vision)
- **Object Detection**: Detect UI elements (planned)
- **HTTP API**: RESTful API for frame analysis

## Requirements

- Tesseract OCR (for text extraction)
  - macOS: `brew install tesseract`
  - Ubuntu: `sudo apt-get install tesseract-ocr`
  - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki

## Running the Service

```bash
cd services/vision
pip install -r requirements.txt
python service.py
```

The API will be available at `http://localhost:8081`.

## API Endpoints

### POST /analyze
Full analysis: OCR + detection + description

```bash
curl -X POST -F "file=@screenshot.jpg" http://localhost:8081/analyze
```

Response:
```json
{
  "frame_id": "frame_1234567890",
  "timestamp": 1699000000.0,
  "ocr_texts": [
    {
      "text": "Submit",
      "confidence": 0.95,
      "bbox": {"x1": 100, "y1": 200, "x2": 200, "y2": 240}
    }
  ],
  "detected_objects": [],
  "description": "Screen shows a form with a submit button",
  "resolution": [1920, 1080],
  "processing_time_ms": 245.6
}
```

### POST /ocr
OCR text extraction only

```bash
curl -X POST -F "file=@screenshot.jpg" http://localhost:8081/ocr
```

### POST /describe
Natural language description only (requires VLM)

```bash
curl -X POST -F "file=@screenshot.jpg" http://localhost:8081/describe
```

## Integration

### With UI Twin
Vision results can augment accessibility data:

```python
# UI Twin provides element structure
# Vision provides visual text and layout

combined_understanding = {
    "accessibility": ui_twin.get_elements(),
    "visual": vision.ocr(frame)
}
```

### With Planner
Vision helps verify actions and understand context:

```python
# After executing action
result = await vision.analyze(current_frame)

# Check if expected text appeared
if "Success" in [r.text for r in result.ocr_texts]:
    print("Action verified visually")
```

## VLM Integration

To enable Vision-Language Model features:

1. Set API key: `export ANTHROPIC_API_KEY=your-key`
2. Update `service.py` to initialize VLM client
3. Uncomment VLM calls in `analyze()` and `describe()`

Example VLM prompt:
```python
"Describe this screenshot in detail, focusing on UI elements, 
 text, and any actions the user might take. Be specific about 
 button labels, form fields, and navigation elements."
```

## Performance

- OCR: ~100-300ms per frame
- VLM: ~1-3s per frame (API call)
- Recommended: Run VLM on-demand, not real-time

## License

Part of the Shail AI system.

