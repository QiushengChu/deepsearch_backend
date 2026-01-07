import os
from typing import Sequence, TypedDict, Annotated, Literal
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START
from model.request_models import AIClarifyResponse
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Command
from model.session_manager import manager
# from concurrent.futures import ThreadPoolExecutor
from model import message_event
from time import time

load_dotenv()


class Clarify_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool


topic_clarify_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).with_structured_output(AIClarifyResponse)
#topic_clarify_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).with_structured_output(AIClarifyResponse)

async def clarify_agent(state: Clarify_State)->Command[Literal["__end__"]]:
    '''The clarify agent will take user's question and clarify it via using tool for taking user's feedback is the question is not clear or too big to analyze'''
    system_prompt = """
    You are a topic clarification agent. Analyze if the query is clear enough. 
    ##Please Note:
    If the query is vague, broad, or lacks specific details, you have to ask clarifying questions.
    """
    system_message = SystemMessage(content=system_prompt)

    all_messages = [system_message] + state["messages"]
    await manager.send_event(thread_id=state["thread_id"], event={
        "type": "clarify_detail",
        "sender": "clarify_agent",
        "content": "clarify agent is trying to clarify question from user",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "timestamp": time()
    })
    response = await topic_clarify_model.ainvoke(all_messages)
    ai_clarify_str = f"need_to_clarify: {response.need_to_clarify}, clarify_question: {response.clarify_question}"
    event = message_event.Event(
        type = "hard_pause",
        sender = "clarify_agent",
        content = response.clarify_question,
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time()
    )
    if response.need_to_clarify: ##AI needs further clarify with user
        await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
        return Command(
            goto="__end__",
            update={"messages": state["messages"] + [AIMessage(content=ai_clarify_str, additional_kwargs={"message_user": True, "message_event": event})],
                    "sender": "clarify_agent",
                    "pause_required": True
                }
        )
    else:
        return Command(goto="__end__", update={
            "messages": state["messages"] + [AIMessage(content=ai_clarify_str, additional_kwargs={"message_user": False, "message_event": event})],
            "sender": "clarify_agent",
            "thread_id": state["thread_id"],
            "pause_required": False
        })
    
clarify_app_graph = StateGraph(Clarify_State)
clarify_app_graph.add_node("clarify_agent", clarify_agent)
clarify_app_graph.add_edge(START, "clarify_agent")
clarify_app = clarify_app_graph.compile()