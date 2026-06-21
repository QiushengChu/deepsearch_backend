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
    path: Literal["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "coding_app", "file_search_app", "__end__"] = Field(description="" \
    "The next application/agent to route to")
    reasoning: str = Field(description="Precise rationale for selecting this path. "
    "CRITICAL: Choose 'coding_agent' ONLY if a specific file path is known and the goal requires modification, execution, or deep code analysis. "
    "Choose 'file_search_agent' ONLY if the exact file path is unknown and you need to discover keywords, locate file names, or read file content first. "
    "State the exact file object, the required operation (e.g., read vs. edit), and the explicit final goal to justify your path selection.")


ROUTE_JSON_SCHEMA = {
    "title": "Route",
    "description": "Route decision for workflow navigation",
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "enum": ["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "file_search_app", "file_generator_app"],
            "description": "The next application/agent to route to, Notice that coding agent will repsonse a big update with possible generated file, analysis result. "
            "Dont route back to coding agent for avoiding dead loop unless user has a different requiring coding agent to do.."
        },
        "reasoning": {
            "type": "string",
            "description": "Precise rationale for selecting this path. "
            "CRITICAL: Choose 'coding_agent' ONLY if a specific file path is known and the goal requires modification, execution, or deep code analysis. "
            "Choose 'file_search_agent' ONLY if the exact file path is unknown and you need to discover keywords, locate file names, or read file content first. "
            "State the exact file object, the required operation (e.g., read vs. edit), and the explicit final goal to justify your path selection."
            "CRISTALLY CLEAR about the sub agent should do, including task, goal, coding/file and other type of objects."
            "IMPORTANT NOTICE: Only giving expection and reason of routing for a single step. NEVER do `routing to A for doing xxx, then b for doing xxx` in a single reason"
            "Notice that coding agent will repsonse a big update with possible generated file, analysis result. "
            "Dont route back to coding app for avoiding dead loop unless user has a different requiring coding agent to do.."
        }
    },
    "required": ["path", "reasoning"],
    "additionalProperties": False
}