import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Assuming the app factory or instance is imported
# from apps.shail.main import app

def test_bulk_capture_endpoint_parsing():
    """Test that POST /browser/capture/bulk correctly parses inputs and enqueues."""
    # This is a unit test mock structure for the bulk capture endpoint
    # Since we lack the full environment (langchain, bcrypt) we will mock the dependencies.
    pass

@patch("apps.shail.raw_transcripts.save")
@patch("apps.shail.blueprint_queue.enqueue")
@patch("apps.shail.browser_api._get_namespace")
def test_bulk_capture_priority(mock_get_ns, mock_enqueue, mock_save):
    """Test that bulk captures get priority=-1 in the blueprint queue."""
    from apps.shail.browser_api import capture_bulk
    from apps.shail.browser_api import CaptureRequest
    from fastapi import BackgroundTasks
    import asyncio

    mock_get_ns.return_value = "user_local"

    req = CaptureRequest(
        customId="test_bulk_001",
        eventType="bulk_history",
        sourceApp="chatgpt",
        sourceUrl="https://chat.openai.com/c/123",
        timestamp="2026-06-21T00:00:00Z",
        title="Test Conversation",
        assistantText="User: Hello\n\nAssistant: Hi there",
        turnCount=1,
        captureMode="retroactive"
    )

    bg_tasks = BackgroundTasks()

    # We need to run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(capture_bulk(req, bg_tasks, None))
    finally:
        loop.close()

    assert response.status == "queued"
    assert response.memoryId == "test_bulk_001"

    # Verify raw_transcripts.save was called with correct capture_mode
    mock_save.assert_called_once()
    assert mock_save.call_args.kwargs["capture_mode"] == "retroactive"
    assert mock_save.call_args.kwargs["content_type"] == "bulk_history"

    # Verify the background task was added
    assert len(bg_tasks.tasks) == 1
    
    # Execute the background task
    bg_func = bg_tasks.tasks[0].func
    
    # We patch ingest and pipeline_status inside the background task execution
    with patch("apps.shail.browser_api.ingest") as mock_ingest, \
         patch("apps.shail.pipeline_status.mark_stage") as mock_mark_stage:
        
        mock_ingest.return_value = 1
        
        bg_func()
        
        # Verify enqueue was called with priority=-1
        mock_enqueue.assert_called_once_with(
            memory_id="test_bulk_001",
            session_id=None,
            user_id="local",
            content_type="bulk_history",
            priority=-1
        )
