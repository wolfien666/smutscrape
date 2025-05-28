# Smutscrape API Server

The smutscrape script can now run as a FastAPI server, allowing you to execute scraping commands via HTTP requests. The API operates asynchronously - scraping tasks run in the background while the API remains responsive.

## Installation

Install the additional API dependencies:

```bash
pip install fastapi uvicorn pydantic
# Or install all requirements including API support:
pip install -r requirements.txt
```

## Configuration

You can configure the API server host and port in `config.yaml`:

```yaml
api_server:
  host: "127.0.0.1"  # Host to bind the API server to
  port: 6999         # Port to bind the API server to
```

Priority order for server settings:
1. Command-line arguments (highest priority)
2. `config.yaml` settings
3. Built-in defaults: `127.0.0.1:6999` (lowest priority)

## Starting the Server

Run smutscrape in server mode:

```bash
# Start with settings from config.yaml (or defaults if not configured)
python scrape.py --server

# Override config with command-line arguments
python scrape.py --server --host 0.0.0.0 --port 8080

# Enable debug logging
python scrape.py --server --debug
```

## API Endpoints

### GET /
Returns API information and available endpoints.

### GET /sites
Lists all supported sites with their configurations.

**Response:**
```json
[
  {
    "code": "ph",
    "name": "PornHub",
    "domain": "pornhub.com",
    "modes": [
      {
        "name": "video",
        "description": "Scrape a single video",
        "supports_pagination": false,
        "examples": ["https://pornhub.com/view_video.php?viewkey=xxx"]
      },
      {
        "name": "model",
        "description": "Scrape all videos from a model",
        "supports_pagination": true,
        "examples": ["Massy Sweet"]
      }
    ],
    "metadata": ["actors", "code", "date", "studios", "tags"],
    "requires_selenium": true,
    "notes": ["Requires Selenium and ChromeDriver"]
  }
]
```

### GET /sites/{code}
Get detailed information about a specific site.

**Parameters:**
- `code`: Site shortcode (e.g., "ph" for PornHub)

### POST /scrape
Execute a scraping command. **Returns immediately** with a task ID for tracking progress.

**Request Body:**
```json
{
  "command": "ph pornstar \"Massy Sweet\"",
  "overwrite": false,
  "re_nfo": true,
  "page": "1",
  "applystate": false,
  "debug": false
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Scraping task started successfully",
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "details": {
    "command": "ph pornstar \"Massy Sweet\"",
    "task_id": "123e4567-e89b-12d3-a456-426614174000"
  },
  "errors": null
}
```

**Validation Error Response (200):**
```json
{
  "success": false,
  "message": "Invalid mode 'foo' for site 'ph'. Available modes: video, model, pornstar",
  "task_id": null,
  "details": null,
  "errors": ["Invalid mode 'foo' for site 'ph'. Available modes: video, model, pornstar"]
}
```

### GET /tasks/{task_id}
Get the status of a specific scraping task.

**Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "running",  // "pending", "running", "completed", "failed"
  "message": null,
  "created_at": "2024-01-20T10:30:00",
  "started_at": "2024-01-20T10:30:01",
  "completed_at": null
}
```

### GET /tasks
List all tasks, optionally filtered by status.

**Query Parameters:**
- `status` (optional): Filter by status (pending, running, completed, failed)

**Example:** `GET /tasks?status=running`

## Usage Examples

### Execute a scrape command
```bash
# Start a scraping task
curl -X POST http://localhost:6999/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "command": "ph pornstar \"Massy Sweet\"",
    "re_nfo": true
  }'

# Response includes task_id
# {"success": true, "message": "Scraping task started successfully", "task_id": "abc-123", ...}

# Check task status
curl http://localhost:6999/tasks/abc-123

# List all running tasks
curl http://localhost:6999/tasks?status=running
```

### Python Client Example

```python
import requests
import time

# Base URL of your smutscrape API
BASE_URL = "http://localhost:6999"

# Start a scraping task
scrape_request = {
    "command": "ph pornstar \"Massy Sweet\"",
    "re_nfo": True,
    "page": "1"
}

response = requests.post(f"{BASE_URL}/scrape", json=scrape_request)
result = response.json()

if result["success"]:
    task_id = result["task_id"]
    print(f"Task started: {task_id}")
    
    # Poll for completion
    while True:
        status_response = requests.get(f"{BASE_URL}/tasks/{task_id}")
        status = status_response.json()
        
        print(f"Status: {status['status']}")
        
        if status["status"] in ["completed", "failed"]:
            print(f"Task {status['status']}: {status.get('message', 'No message')}")
            break
            
        time.sleep(5)  # Check every 5 seconds
else:
    print(f"Error: {result['message']}")
```

## Notes

- The API validates commands before starting tasks - invalid commands return immediately with an error
- Multiple scraping tasks can run concurrently (default: 4 workers)
- Task history is kept in memory (last 100 tasks)
- All CLI features work identically: state tracking, VPN rotation, Selenium support, etc.
- The API server remains responsive while scraping tasks run in the background 