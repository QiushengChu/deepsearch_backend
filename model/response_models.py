from pydantic import BaseModel
from typing import Optional

class SessionStatusResponse(BaseModel):
    thread_id: str
    status: str
    current_agent: Optional[str]
    has_interruption: bool

    