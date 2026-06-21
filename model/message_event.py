from pydantic import BaseModel
from typing import List

class Event(BaseModel):
    type: str = None
    sender: str = None
    content: str = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    links: List[str] = []
    timestamp: float
    fileNames: List[str] = []
    message_user: bool = True
    error: bool = False
