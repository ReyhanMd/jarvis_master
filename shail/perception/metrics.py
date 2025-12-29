from prometheus_client import Counter, Gauge, Histogram

# Counters
grounding_attempts_total = Counter("shail_grounding_attempts_total", "Total grounding attempts")
grounding_success_total = Counter("shail_grounding_success_total", "Successful groundings")
frames_requested_total = Counter("shail_frames_requested_total", "Frames requested from CaptureService")
vlm_calls_total = Counter("shail_vlm_calls_total", "VLM API calls made")
user_guidance_requests_total = Counter("shail_user_guidance_total", "Human-in-loop escalations")

# Histograms
grounding_confidence = Histogram("shail_grounding_confidence", "Grounding confidence scores")
vision_latency_seconds = Histogram("shail_vision_latency_seconds", "VisionAgent latency")
vlm_tokens_used = Histogram("shail_vlm_tokens_used", "Tokens per VLM call")

# Gauges
buffer_events_count = Gauge("shail_buffer_events", "Events in GroundingBuffer")
buffer_frames_count = Gauge("shail_buffer_frames", "Frames in GroundingBuffer")

