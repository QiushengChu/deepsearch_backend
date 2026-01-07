import os
from typing import Sequence, TypedDict, Annotated, Literal
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START
from model.request_models import Topics
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Command
from model.session_manager import manager
# from concurrent.futures import ThreadPoolExecutor
from utils.context import context_purifier
from model import message_event
from time import time


load_dotenv()

class Summary_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    summarized_topics: Sequence[str]
    sender: str
    thread_id: str
    pause_required: bool

##enforce structured output
topic_summary_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Topics)
#topic_summary_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).with_structured_output(Topics)

async def topic_summary_agent(state: Summary_State)-> Command[Literal["__end__"]]:
    '''
    this topic summary agent is responsible for summarizing the the conversation with user's input into 2 key topics, the topics must contain what user is truely looking for
    '''
    system_prompt = "This is topic summary agent. For summarizing the conversation into 2 key topics which will be used for other search agent to process. NOTE: the topics must contain what user is truely looking for"

    all_messages = [SystemMessage(content=system_prompt)] + state["messages"]
    converted_messages = context_purifier(state_messages=all_messages)
    response = await topic_summary_model.ainvoke(converted_messages)
    ## response is already a Topics Oject 
    ai_message = AIMessage(content=response.to_str())
    event = message_event.Event(
        type= "summarize_topics",
        sender = "topic_summary_agent",
        content = f"research topic has been summarized into {response.to_str()}",
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time()
    )
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
    ai_message.additional_kwargs={"message_user": True, "message_event": event}
    return Command(
        goto="__end__",
        update={
            "messages": state["messages"] + [ai_message],
            "summarized_topics": response.topics,
            "sender": "topic_summary_agent",
            "thread_id": state["thread_id"]
        }
    )


topic_summary_app_graph = StateGraph(Summary_State)
topic_summary_app_graph.add_node("topic_summary_agent", topic_summary_agent)
topic_summary_app_graph.add_edge(START, "topic_summary_agent")
topic_summary_app = topic_summary_app_graph.compile()
