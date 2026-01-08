import os
from model.file_parser import Chromadb_agent
from langgraph.graph import StateGraph, START
from typing import TypedDict, Sequence, Annotated, Literal, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.types import Command
from langchain_deepseek import ChatDeepSeek
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, InjectedState
from dotenv import load_dotenv
from model import message_event
from model.session_manager import manager
from time import time
from pydantic import BaseModel, Field



load_dotenv()

class Search_Sentence_Collection(BaseModel):
    """Model for ChromaDB Search Parameters"""
    search_sentences: List[str] = Field(..., description="The search queries or keywords to find relevant content")
    file_name: str = Field(..., description="The specific file name to search within (e.g., 'document.pdf')")


class File_Search_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool
    message_user: bool
    tool_call_id: str

chromadb_search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), temperature=0, top_p=0.1)

@tool
async def chromadb_search(search_collection_list: List[Search_Sentence_Collection], thread_id: Annotated[str, InjectedState("thread_id")], tool_call_id: Annotated[str, InjectedState("tool_call_id")])->ToolMessage:
    """
    Search for relevant information in uploaded files using ChromaDB.
    
    This tool searches through chunked and indexed file content to find passages
    relevant to your search queries. Each search can target a specific file.
    
    Args:
        search_collection_list: List of search parameters, each containing:
            - search_sentences: The query or keywords to search for
            - file_name: The specific file to search within
        thread_id: The current session ID (automatically injected)
    
    Returns:
        Formatted search results with relevant passages from the specified files   
    Example:
        To search for "neural networks" in "ai_paper.pdf":
        [{"search_sentences": ["neural networks", "RHLF"], "file_name": "ai_paper.pdf"}]
    """
    system_prompt = "Please summarize the contents extracted from the the files, the output should be " \
    "file: $file_name, relevent_content: $summary. Please Notice there are might be irrelevant information or duplicates in content chunks"

    MAX_RESULTS = 20
    DISTANCE_THRESHOLD = 1.7
    all_results = []

    chromadb_agent = Chromadb_agent()
    for search_params in search_collection_list:
        try:
            collecion_name = f"{thread_id}_{search_params.file_name}"
            collection = chromadb_agent.chromadb_client.get_collection(collecion_name)

            ##perform search query
            results = collection.query(
                query_texts=search_params.search_sentences,
                n_results=MAX_RESULTS,
                include=["documents", "metadatas", "distances"]
            )
            if results["ids"][0]:
                ##Filter by similarity threshold
                for i, distance in enumerate(results["distances"][0]):
                    if distance < DISTANCE_THRESHOLD:
                        all_results.append(str({
                            "file": search_params.file_name,
                            "queries": search_params.search_sentences,
                            "content": results["documents"][0][i]
                        }))
        except ValueError:
            all_results.append(str({
                "file": search_params.file_name,
                "query": search_params.search_sentences,
                "error": f"File '{search_params.file_name}' not found in session"
            }))
        except Exception as e:
            all_results.append(str({
                "file": search_params.file_name,
                "query": search_params.search_sentences,
                "error": str(e)
            }))

    if all_results:
        raw_relevant_contents = "\n".join(all_results)
        response = await chromadb_search_model.ainvoke(
            [SystemMessage(system_prompt)] + [AIMessage(raw_relevant_contents)] 
        )
        event = message_event.Event(
            type = "file search agent has summarized the result ",
            sender = "file_search_tool",
            content = response.content,
            input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
            output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
            total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
            timestamp = time()
        )
        return ToolMessage(
            tool_call_id=tool_call_id, 
            content=response.content, 
            additional_kwargs={
                "sender": "file_search_tool", 
                "message_user": False,
                "message_event": event.model_dump(),
                "timestamp": time()
            }
        )
    else:
        event = message_event.Event(
            type = "file search agent cannot find related information ",
            sender = "file_search_tool",
            content = "No relevant information found in the uploads",
            input_tokens = 0,
            output_tokens = 0,
            total_tokens = 0,
            timestamp = time()
        )
        return ToolMessage(
            tool_call_id=tool_call_id, 
            content="No relevant information found in the uploads", 
            additional_kwargs={
                "sender": "file_search_tool", 
                "message_user": False,
                "message_event": event.model_dump(),
                "timestamp": time()
            }
        )


file_search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), temperature=0, top_p=0.1).bind_tools([chromadb_search])

async def file_search_agent(state: File_Search_State)->Command[Literal["__end__", "chromadb_search"]]:
    '''
    The purpose of the file_search_agent is for finding the relevant information from the uploaded file chunked and 
    indexed in the chromadb 
    '''
    system_prompt = "You are the file search agent, according to latest user prompt, the the most relevant information which can help to answer the question"

    response = await file_search_model.ainvoke(state["messages"] + [SystemMessage(content=system_prompt)])
    event = message_event.Event(
        type = "file_search_agent",
        sender = "file_search_agent",
        content = "Enough Infomration Found.." if not response.tool_calls else "Sending to file search tool for getting more information",
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time()
    )

    response.additional_kwargs = {"message_user": True, "message_event": event}
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
    if hasattr(response, "tool_calls") and response.tool_calls:
        return Command(
            goto=response.tool_calls[0].get("name", "__end__"),
            update={
                "messages": state["messages"] + [response],
                "sender": "file_search_agent",
                "thread_id": state["thread_id"],
                "pause_required": False,
                "message_user": True,
                "tool_call_id": response.tool_calls[0]['id']
            }
        )
    else:
        return Command(
            goto="__end__",
            update={
                "messages": state["messages"] + [response],
                "thread_id": state["thread_id"],
                "sender": "file_search_agent"
            }
        )

file_search_app_graph = StateGraph(File_Search_State)
file_search_app_graph.add_node("file_search_agent", file_search_agent)
file_search_app_graph.add_node("chromadb_search", ToolNode([chromadb_search]))
file_search_app_graph.add_edge(START, "file_search_agent")
file_search_app_graph.add_edge("chromadb_search", "file_search_agent")
file_search_app = file_search_app_graph.compile()