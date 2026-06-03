from pydantic import BaseModel, Field
from typing import Literal

class AgentForward(BaseModel):
    spec: str | None = Field(default=None, description="""Detailed summary of the user's coding task when task is about to start. MUST include:
    1. Goal: What the user wants to achieve
    2. User-provided data: Copy the EXACT details user provided (names, content, datasets, etc.). DO NOT paraphrase or generalize.
    3. Output: Expected file format, file name, path
    4. Constraints: Libraries, style, language requirements""")
    task_complete_summary: str | None = Field(default=None, description="The summarization of the completed task when task is complete")
    output_obj_path: list[str] | None = Field(default=None, description="The file path of the generated output artifacts (e.g. PDF, CSV, image, report). Populate this ONLY if the user's goal is to produce a downloadable file or document. Set to None if the user wants a text-based analysis result instead. If artifact(s) is generated, No need to have output_result")
    output_result: str | None = Field( default=None, description="The final text response to the user. Use this when the user wants an analytical result, summary, or insight (e.g. data analysis, statistics, predictions). Only When user is asking for analsis related topic")
       
    
    @staticmethod
    def to_str(agent_forward: "AgentForward")->str:
        '''
        convert to str
        '''
        return f"forward to {'__end__' if agent_forward.output_obj_path or agent_forward.output_result else 'code_planner'}, reason: {agent_forward.reason}"
    
class Plans(BaseModel):
    todo_md: str = Field(..., description="The content for the todo.md file where each task and its progress is explicitly defined..")
    plans: list[str] = Field(..., description="The string list of REMAINING tasks (NO COMPLETED tasks)")

class Todo(BaseModel):
    todo_md: str = Field(..., description="The content for the todo.md file where each task and its progress is explicitly defined..")
    
class Code(BaseModel):
    code_text: str | None = Field(default=None, description="The python code in string for the current task")
    file_name: str | None = Field(default=None, description="The file name of the code")

class CodeList(BaseModel):
    code_list: list[Code] = Field(default=[], description="The list of Code object. Each of them contains code_text and file_name")
    exe_cmd: list[str] = Field(default=[], description="The list of cmd executions, Notice command 'python ' will be used in runtime", examples=["python main.py"])

class Problem(BaseModel):
    max_retries: int = Field(default=5, description="Maxiumn number of retry for the specific problem")
    stratch_notepad: str | None = Field(default=None, description="Error description of the problem")
    code_fix: CodeList | None = Field(default=None, description="Code fix of the problem")
