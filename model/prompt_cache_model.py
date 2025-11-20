from typing import Dict, List
from pydantic import BaseModel
from collections import defaultdict

class Prompt(BaseModel):
    type: str
    content: str

class PromptCacheInMemory:
    def __init__(self):
        self.session: Dict[str, List[Prompt]] = defaultdict(list)

prompt_cache = PromptCacheInMemory()