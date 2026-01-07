import os, asyncio, json
from time import time
from typing import TypedDict, Annotated, Sequence, List, Literal
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages
from langchain_deepseek import ChatDeepSeek
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.tools import tool
from tavily import AsyncTavilyClient
from model.session_manager import manager
import model.message_event as message_event
from langgraph.types import Command
from langgraph.graph import START, StateGraph
from dotenv import load_dotenv

load_dotenv()

class Search_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    search_count: int
    sender: str
    thread_id: str
    tool_call_id: str
    pause_required: bool
    total_links: int



search_summary_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0)
#search_summary_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0)

@tool
async def search_tool(topics: List[str], thread_id: Annotated[str, InjectedState("thread_id")], tool_call_id: Annotated[str, InjectedState("tool_call_id")])->ToolMessage: ##inject thread_id here
    '''
    search_tool is for finding the relevant information over the internet via the tavily client
    Args:
        topics(List[str]): the list of search topics that the search tool will need to search the relevant information
    Return:
        a list of dict of the information of each topics
    '''
    tavily_api_key = os.getenv("tavily_api_key")
    client = AsyncTavilyClient(api_key=tavily_api_key)
    # with ThreadPoolExecutor(max_workers=5) as executor:
    #     results = await list(executor.map(lambda topic: client.search(topic), topics))
    corotines = [client.search(topic) for topic in topics]
    # task_list = asyncio.create_task(corotines)
    results = await asyncio.gather(*corotines)
    total_links = []
    max_response_time = 0
    mapped_results = []
    for each in results:
        mapped_results.append({
            "query": each["query"],
            "results": [ {k: v for k, v in single_source.items() if k != "url"} for single_source in each["results"]]
        })
        total_links.extend([x["url"] for x in each["results"]])
        max_response_time = max_response_time if each["response_time"] < max_response_time else each["response_time"]
    # links_text = '\n'.join(total_links)
    await manager.send_event(thread_id=thread_id, event={
        "type": "search_event",
        "sender": "search_agent",
        "content": f"found the results from the following links about the breakdown research topics.",
        "links": total_links,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "timestamp": time()
    })
    ##need to summarize the search result to avoid gargage information in the search result
    system_message ='''Please summarize the search result without losing any important information but remove all irrelevance, such as invalid chars, ads etc
    These are the topics:{}
    '''.format(', '.join(topics))
    all_messages = [SystemMessage(content=system_message)] + [HumanMessage(content=json.dumps({"mapped_results": mapped_results}).encode().decode('unicode_escape'))]
    response = await search_summary_model.ainvoke(all_messages)
    event = message_event.Event(
        type = "search_event",
        sender = "search_agent",
        content = "search_agent is summarizing the search result",
        links = total_links,
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp=time()
    )
    await manager.send_event(thread_id=thread_id, event=event.model_dump())
    return ToolMessage(
        tool_call_id=tool_call_id, 
        content=response.content, 
        additional_kwargs={
            "max_response_time": max_response_time, 
            "total_num_links": len(total_links), 
            "sender": "search_tool", 
            "num_links": total_links,
            "message_user": False,
            "message_event": event.model_dump(),
            "links": total_links,
            "timestamp": time()
        }
    )

search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).bind_tools([search_tool])
#search_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).bind_tools([search_tool])

async def search_agent(state: Search_State)->Command[Literal["__end__", "search_tool"]]:
    '''This search agent will search the relevant information about the search topics via the search tool I provide'''
    init_system_prompt = "search agent will be using the search tool for fidning the relevant information from the internet." \
    "for search the information you MUST use the search tool I provide"
    followup_systme_prompt = "You should decide whether the information search tool found is enough to answer the question or not, if not please give the topic list on what should be searched next"
    system_prompt = followup_systme_prompt if isinstance(state["messages"][-1], ToolMessage) else init_system_prompt
    
    ##state["messages"][-1].additional_kwargs["total_num_links"]
    all_messages = state["messages"] + [SystemMessage(content=system_prompt)] 
    response = await search_model.ainvoke(all_messages)
    event = message_event.Event(
        type = "search agent summarizing results",
        sender = "search_agent",
        content = response.content,
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time()
    )
    response.additional_kwargs = {"message_user": False, "message_event": event.model_dump()}
    if hasattr(response, "tool_calls") and response.tool_calls:
        return Command(
            goto="search_tool",
            update={
                "messages": state["messages"] + [response],
                "sender": "search_agent",
                "search_count": len(response.tool_calls[0]["args"]["topics"]),
                "thread_id": state["thread_id"],
                "tool_call_id": response.tool_calls[0]['id']
            }
        )
    else:
        return Command(
            goto="__end__",
            update={
                "messages": state["messages"] + [response],
                "sender": "search_agent",
                "thread_id": state["thread_id"]
            }
        )
    

search_app_graph = StateGraph(Search_State)
search_app_graph.add_node("search_agent", search_agent)
search_app_graph.add_node("search_tool", ToolNode([search_tool]))
search_app_graph.add_edge(START, "search_agent")
search_app_graph.add_edge("search_tool", "search_agent")
search_app = search_app_graph.compile()