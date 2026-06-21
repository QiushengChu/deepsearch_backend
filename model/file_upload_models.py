from pydantic import BaseModel, Field
from typing import Literal


class UploadedFile(BaseModel):
    file_name: str = Field(..., description="the name of the file")
    estimated_tokens: int = Field(default=0, description="number of the tokens")
    process_method: Literal["file_search", "coding"]
    result: bool = Field(..., description="if indexed successfully")