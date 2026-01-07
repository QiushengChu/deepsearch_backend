import os
from typing import TypedDict, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import START, StateGraph
from langgraph.types import Command
import model.message_event as message_event
from utils.context import context_purifier
from time import time
from model.session_manager import manager
from dotenv import load_dotenv

load_dotenv()

class Report_Writer_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool

report_writer_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"))
#report_writer_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0)

async def report_writer_agent(state: Report_Writer_State)-> Command[Literal["__end__"]]:
    '''
    The report write agent is for summarizing the search results into a small report
    '''
    system_prompt = "You are professional report writer good at summarizing the previous conversation and search result into a formal report and also quick responder." \
    "Please make sure you can complete the task and DONT add any fake information there, unless it is a educated guess. Please note the information are enough for you to generate a report and generate the report DIRECTLY. Or if the user is requesting a short anwser please just anwser the question instead of generating a formal report."

    system_message = SystemMessage(content=system_prompt)
    converted_messages = []
    converted_messages = context_purifier(state_messages=state["messages"])
    all_messages = converted_messages + [system_message]
    response = await report_writer_model.ainvoke(all_messages)
    print(response.text)
    event = message_event.Event(
        type = "report_writer_event",
        sender = "report_writer_agent",
        content = response.text,
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time()

    )
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
    response.additional_kwargs = {"message_user": True, "message_event": event}
    return Command(
        goto="__end__",
        update={
            "messages": state["messages"] + [response],
            "sender": "report_writer_agent",
            "thread_id": state["thread_id"]
        }
    )

report_writer_app_graph = StateGraph(Report_Writer_State)
report_writer_app_graph.add_node(report_writer_agent, "report_writer_agent")
report_writer_app_graph.add_edge(START, "report_writer_agent")
report_writer_app = report_writer_app_graph.compile()