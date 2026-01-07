from pydantic import BaseModel
from typing import Optional, List

class Event(BaseModel):
    type: str
    sender: str
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    links: Optional[List[str]] = None
    timestamp: float