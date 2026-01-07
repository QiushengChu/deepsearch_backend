from pydantic import BaseModel, Field
from typing import Literal

class ChatRequest(BaseModel):
    user_id: str
    message: str


class UserClarify(BaseModel):
    type: str
    message: str
    thread_id: str

class AIClarifyResponse(BaseModel):
    need_to_clarify: bool
    clarify_question: str

    def to_str(self)->str:
        return f"need_to_clarify: {self.need_to_clarify}, clarify_question: {self.clarify_question}"


class Topics(BaseModel):
    topics: list[str]

    def to_str(self)->str:
        return ", ".join(self.topics)
    
    
class Route(BaseModel):
    path: Literal["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "__end__"] = Field(description="" \
    "The next application/agent to route to")
    reasoning: str = Field(description="Brief explaination of why this path is selected")


ROUTE_JSON_SCHEMA = {
    "title": "Route",
    "description": "Route decision for workflow navigation",
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "enum": ["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "file_search_app"],
            "description": "The next application/agent to route to"
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why this path is selected"
        }
    },
    "required": ["path", "reasoning"],
    "additionalProperties": False
}