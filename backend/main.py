from __future__ import annotations

"""FastAPI application entry-point for the recipe chatbot."""

from pathlib import Path
from typing import Final, List, Dict
import datetime
import json

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.utils import get_agent_response  # noqa: WPS433 import from parent

# -----------------------------------------------------------------------------
# Application setup
# -----------------------------------------------------------------------------

APP_TITLE: Final[str] = "Recipe Chatbot"
app = FastAPI(title=APP_TITLE)

# Serve static assets (currently just the HTML) under `/static/*`.
STATIC_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# -----------------------------------------------------------------------------
# Request / response models
# -----------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """Schema for a single message in the chat history."""
    role: str = Field(..., description="Role of the message sender (system, user, or assistant).")
    content: str = Field(..., description="Content of the message.")

class ChatRequest(BaseModel):
    """Schema for incoming chat messages."""

    messages: List[ChatMessage] = Field(..., description="The entire conversation history.")


class ChatResponse(BaseModel):
    """Schema for the assistant's reply returned to the front-end."""

    messages: List[ChatMessage] = Field(..., description="The updated conversation history.")


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest) -> ChatResponse:  # noqa: WPS430
    """Main conversational endpoint.

    It proxies the user's message list to the underlying agent and returns the updated list.
    """
    # Convert Pydantic models to simple dicts for the agent
    request_messages: List[Dict[str, str]] = [msg.model_dump() for msg in payload.messages]

    try:
        updated_messages_dicts = get_agent_response(request_messages)
    except Exception as exc:  # noqa: BLE001 broad; surface as HTTP 500
        # In production you would log the traceback here.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    response = ChatResponse(messages=[ChatMessage(**msg) for msg in updated_messages_dicts])

    # Save trace (request and response). If an existing trace file is present,
    # reuse it by appending; otherwise, create a new one.
    traces_dir = Path(__file__).parent.parent / "annotation" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # Choose an existing .json file if available (most recently modified),
    # otherwise create a new timestamped file.
    existing_json_files = sorted(
        traces_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if existing_json_files:
        trace_path = existing_json_files[0]
    else:
        trace_path = traces_dir / f"trace_{ts}.json"

    new_entry = {
        "ts": ts,
        "request": payload.model_dump(),
        "response": response.model_dump(),
    }

    # Try to maintain valid JSON by using an array in the file. If the existing
    # file contains a single JSON object, wrap it into a list and append. If the
    # file is newline-delimited JSON, fall back to appending a JSON line.
    if trace_path.exists():
        try:
            existing_content = trace_path.read_text(encoding="utf-8").strip()
            if not existing_content:
                data = []
            else:
                parsed = json.loads(existing_content)
                if isinstance(parsed, list):
                    data = parsed
                else:
                    data = [parsed]
            data.append(new_entry)
            trace_path.write_text(json.dumps(data), encoding="utf-8")
        except json.JSONDecodeError:
            # Fallback to JSON Lines append if the file isn't valid JSON array/object
            with open(trace_path, "a", encoding="utf-8") as f:
                if existing_content and not existing_content.endswith("\n"):
                    f.write("\n")
                f.write(json.dumps(new_entry) + "\n")
    else:
        # Create a new file with a JSON array holding the first entry
        trace_path.write_text(json.dumps([new_entry]), encoding="utf-8")

    return response


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:  # noqa: WPS430
    """Serve the chat UI."""

    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frontend not found. Did you forget to build it?",
        )

    return HTMLResponse(html_path.read_text(encoding="utf-8")) 