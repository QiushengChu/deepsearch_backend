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
import re

load_dotenv()

class Search_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    search_count: int
    sender: str
    thread_id: str
    tool_call_id: str
    pause_required: bool
    total_links: int


def clean_text(text) -> str:
    """Remove invalid Unicode characters including surrogates"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    
    # Remove surrogate characters (U+D800 to U+DFFF)
    cleaned = re.sub(r'[\ud800-\udfff]', '', text)
    # Remove other problematic characters
    cleaned = cleaned.encode('utf-8', errors='ignore').decode('utf-8')
    
    return cleaned

def clean_dict(d) -> dict:
    """Recursively clean all strings in a dictionary"""
    if not isinstance(d, dict):
        return d
    
    cleaned = {}
    for key, value in d.items():
        if isinstance(value, str):
            cleaned[key] = clean_text(value)
        elif isinstance(value, dict):
            cleaned[key] = clean_dict(value)
        elif isinstance(value, list):
            cleaned[key] = [
                clean_dict(item) if isinstance(item, dict)
                else clean_text(item) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned

def safe_json_dumps(obj) -> str:
    """Safely convert object to JSON string"""
    try:
        if isinstance(obj, dict):
            obj = clean_dict(obj)
        elif isinstance(obj, list):
            obj = [clean_dict(item) if isinstance(item, dict) else item for item in obj]
        
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"JSON encoding error: {e}, falling back to ensure_ascii=True")
        return json.dumps(obj, ensure_ascii=True, default=str)


search_summary_model = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=os.getenv("api_key"), 
    top_p=0.1, temperature=0,
    extra_body={"thinking": {"type": "disabled"}}
)

@tool
async def search_tool(
    thread_id: Annotated[str, InjectedState("thread_id")], 
    tool_call_id: Annotated[str, InjectedState("tool_call_id")],
    topics: List[str] = [], 
) -> ToolMessage:
    '''
    search_tool is for finding the relevant information over the internet via the tavily client
    Args:
        topics(List[str]): the list of search topics that the search tool will need to search the relevant information
    Return:
        ToolMessage with summarized search results
    '''
    try:
        tavily_api_key = os.getenv("tavily_api_key")
        client = AsyncTavilyClient(api_key=tavily_api_key)
        
        corotines = [client.search(topic) for topic in topics]
        results = await asyncio.gather(*corotines)
        
        total_links = []
        max_response_time = 0
        mapped_results = []
        
        for each in results:
            # Clean query
            query = clean_text(each.get("query", ""))
            
            # Clean and process results
            cleaned_results = []
            for single_source in each.get("results", []):
                cleaned_source = {
                    k: clean_text(v) if isinstance(v, str) else v 
                    for k, v in single_source.items() 
                    if k != "url"
                }
                cleaned_results.append(cleaned_source)
                
                if "url" in single_source:
                    total_links.append(single_source["url"])
            
            mapped_results.append({
                "query": query,
                "results": cleaned_results
            })
            
            max_response_time = max(max_response_time, each.get("response_time", 0))
        
        # Send event
        event = message_event.Event(
            type = "search_event",
            sender = "search_agent",
            content = f"Found results from {len(total_links)} links.",
            links = total_links,
            input_tokens = 0,
            output_tokens = 0,
            total_tokens = 0,
            timestamp = time(),
            message_user = True
        )
        await manager.send_event(thread_id=thread_id, event=event.model_dump())
        
        # Summarize with safe JSON
        system_message = f'''Please summarize the search result without losing any important information but remove all irrelevance.
Topics: {', '.join(topics)}
'''
        
        results_json = safe_json_dumps({"mapped_results": mapped_results})
        
        all_messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=results_json)
        ]
        
        response = await search_summary_model.ainvoke(all_messages)
        
        # Clean response
        cleaned_response = clean_text(response.content)
        
        return ToolMessage(
            tool_call_id=tool_call_id,
            content=cleaned_response,
            additional_kwargs={**event.model_dump(), "message_user": False}
        )
        
    except Exception as e:
        print(f"Search tool error: {e}")
        event = message_event.Event(
            type = "search_tool_error",
            sender = "search_agent",
            message_user = False,
            error = True,
            timestamp = time()
        )
        return ToolMessage(
            tool_call_id=tool_call_id,
            content=f"Search encountered an error: {str(e)}",
            additional_kwargs=event.model_dump()
        )


search_model = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=os.getenv("api_key"),
    extra_body={"thinking": {"type": "disabled"}}
).bind_tools([search_tool])
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
        timestamp = time(),
        message_user = False
    )
    response.additional_kwargs = event.model_dump()
    if hasattr(response, "tool_calls") and response.tool_calls:
        return Command(
            goto="search_tool",
            update={
                "messages": state["messages"] + [response],
                "sender": "search_agent",
                "search_count": len(response.tool_calls[0]["args"].get("topics", [])),
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