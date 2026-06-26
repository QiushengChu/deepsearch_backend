import os
from typing import TypedDict, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import START, StateGraph
from langgraph.types import Command
import model.message_event as message_event
from utils.context import context_purifier
from utils.helper_funcs import safely_ainvoke
from time import time
from model.session_manager import manager
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

class Report_Writer_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    ui_messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool

class File_Generation_Check(BaseModel):
    related_file_generated: bool = Field(..., description="If there is any related file generated")
    file_names: list[str] = Field(..., description="the name of the related files")
    

report_writer_model = ChatDeepSeek(model="deepseek-chat", 
    api_key=os.getenv("api_key"), 
    extra_body={"thinking": {"type": "disabled"}}
)
file_generation_check_model = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=os.getenv("api_key"),
    extra_body={"thinking": {"type": "disabled"}}
).with_structured_output(File_Generation_Check)
#report_writer_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0)

async def report_writer_agent(state: Report_Writer_State)-> Command[Literal["__end__"]]:
    '''
    The report write agent is for summarizing the search results into a small report
    '''
    system_prompt = f"""You are a concise response writer that summarizes ACTIONS TAKEN, not topics discussed.
    YOUR ROLE:
        - Summarize what was ACTUALLY DONE for the user
        - Provide file download links if files were generated
        - Answer the user's SPECIFIC question, not related topics

        ⚠️ CRITICAL RULES:
        1. Focus on WHAT WAS DONE, not general information about the topic
        2. If a file was generated, briefly explain what changes were made and provide the link
        3. Do NOT generate generic reports about the topic (e.g., "FAANG interview tips")
        4. Do NOT add information the user didn't ask for
        5. Keep responses concise and action-focused

        EXAMPLES:

        ❌ BAD (Topic-focused, adds unrequested info):
        User asked to update CV for FAANG.
        Response: "Here's a comprehensive guide to FAANG interviews... 
        1.0 Executive Summary about algorithms...
        2.0 Interview Process..."

        ✅ GOOD (Action-focused, concise):
        User asked to update CV for FAANG.
        Response: "I've analyzed your CV and made the following improvements to align with FAANG requirements:
        - Restructured skills section to highlight relevant technologies
        - Enhanced bullet points with quantifiable achievements
        - Added keywords commonly sought by FAANG recruiters

        Download your updated CV: [link]"

        YOUR TASK:
        - What did the user originally ask for?
        - What actions were taken to fulfill that request?
        - Summarize the result concisely
        - Provide download links if files were generated
        - If user is asking a research or analysis question, provide DETAIL analysis

        Session ID: {state['thread_id']}
        """

    converted_messages = context_purifier(state_messages=state["messages"])

    file_generation_prompt = "Please analyze the whole conversation and anwser if there is related file created by file_generator_app to user's requirement. If there is, return True and the file name. Otherwise return False and file name is None"
    file_check_result = await file_generation_check_model.ainvoke(state["messages"] + [SystemMessage(content=file_generation_prompt)])
    if file_check_result.related_file_generated:
        system_prompt += f"\nIn the response, MUST include the newly created files via prefix http://localhost:8000/api/file/coding_space/{state['thread_id']}/ + {file_check_result.file_names} in the way matching the user's prompt context, using markdown format for file links"

    system_message = SystemMessage(content=system_prompt)

    all_messages = converted_messages + [system_message]
    response = await safely_ainvoke(model=report_writer_model, message_sequence=all_messages, null_response_model_switch=True, circuit_break_threshold=3, response_schema=File_Generation_Check)
    # response = await report_writer_model.ainvoke(all_messages)
    # print(response.text)
    event = message_event.Event(
        type = "report_writer_event",
        sender = "report_writer_agent",
        content = response.text,
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time(),
        fileNames = file_check_result.file_names,
        message_user = True

    )
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump(), message_type="ui_message") ##for UI message streaming
    response.additional_kwargs = event.model_dump()
    return Command(
        goto="__end__",
        update={
            "messages": [response],
            "ui_messages": [response],
            "sender": "report_writer_agent",
            "thread_id": state["thread_id"]
        }
    )

report_writer_app_graph = StateGraph(Report_Writer_State)
report_writer_app_graph.add_node(report_writer_agent, "report_writer_agent")
report_writer_app_graph.add_edge(START, "report_writer_agent")
report_writer_app = report_writer_app_graph.compile()