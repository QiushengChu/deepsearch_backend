import os
import asyncio
from model.file_parser import Chromadb_agent
from langgraph.graph import StateGraph, START
from typing import TypedDict, Sequence, Annotated, Literal, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, SystemMessage, HumanMessage
from langgraph.types import Command
from langchain_deepseek import ChatDeepSeek
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, InjectedState
from dotenv import load_dotenv
from model import message_event
from model.session_manager import manager
from time import time
from pydantic import BaseModel, Field
from collections import defaultdict
import bm25s.high_level as bm25
from chromadb.api.models.Collection import Collection
from langgraph.errors import GraphRecursionError
from langchain_openai import ChatOpenAI



load_dotenv()

class Search_Sentence_Collection(BaseModel):
    """Model for ChromaDB Search Parameters"""
    search_sentences: List[str] = Field(..., description="The search queries or keywords to find relevant content")
    file_name: str = Field(..., description="The specific file name to search within (e.g., 'document.pdf')")


class File_Search_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    internal_messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool
    message_user: bool
    tool_call_id: str
    search_round: int

summary_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), temperature=0, top_p=0.1)
MAX_SEARCH_ATTEMPTS = 5

def vector_search_sort(
        collection: Collection,
        search_words: list[str],
        file_name: str
    )->list[tuple]:
    '''
    searching chromadb chunks via search keywords in ONE collections
    return sorted list of tuple (id, distance, document)
    '''
    DISTANCE_THRESHOLD = 1.7
    MAX_RESULTS = 20
    try:
        ##perform search query in the vector DB
        results = collection.query(
            query_texts=search_words,
            n_results=MAX_RESULTS,
            include=["documents", "metadatas", "distances"]
        )
        ##merge and scored each chunk
        filtered_chunks = []
        if results["ids"]:
            for id in range(len(results["ids"])): ## for example there are 4 search words for the prompt
                merged_chunks = list(zip(results["ids"][id], results["distances"][id], results["documents"][id]))
                filtered_chunks += [each for each in merged_chunks if each[1] < DISTANCE_THRESHOLD]
        filtered_chunks.sort(key=lambda x:x[1])
        return filtered_chunks
    except ValueError:
        return [str({
            "file": file_name,
            "query": search_words,
            "error": f"File '{file_name}' not found in session"
        })]
    except Exception as e:
        return [str({
            "file": file_name,
            "query": search_words,
            "error": str(e)
        })]
    
def bm25_search_sort(
        collection: Collection, 
        search_keywords: list[str],
    )->list[dict]:
    '''
    return list of sorted and merged dict {"id": 1, "score": 1.1, "document": "xxx"}
    '''
    all_chunks = collection.get(include=["documents"])
    retriever = bm25.index(all_chunks["documents"])
    bm25_results =[each_chunk for each in retriever.search(search_keywords) for each_chunk in each]
    filterd_bm25_results = [each for each in bm25_results if each["score"] > 0]
    filterd_bm25_results.sort(key=lambda x: x["score"], reverse=True)
    return filterd_bm25_results



@tool
async def chromadb_search(
    search_collection_list: List[Search_Sentence_Collection], 
    thread_id: Annotated[str, InjectedState("thread_id")], 
    tool_call_id: Annotated[str, InjectedState("tool_call_id")]
)->ToolMessage:
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
    ##for vector db search
    K = 60
    all_results = []

    chromadb_agent = Chromadb_agent()
    for search_params in search_collection_list:
        scored_chunks = defaultdict(lambda: {"score": 0, "id": None})
        try:
            normalized_collection_name = Chromadb_agent.collection_name_normalize(session_id=thread_id, filename=search_params.file_name)
            collection = chromadb_agent.chromadb_client.get_collection(normalized_collection_name)
            ## vector db search
            filtered_chunks = await asyncio.to_thread(vector_search_sort, collection, search_params.search_sentences, search_params.file_name)

            ## bm25 serch
            filterd_bm25_results = await asyncio.to_thread(bm25_search_sort, collection, search_params.search_sentences)
            
            for rank, (chunk_id, _, chunk) in enumerate(filtered_chunks):
                scored_chunks[chunk]["score"] += 1 / (K + rank)
                scored_chunks[chunk]["id"] = int(chunk_id.split("_")[-1])
            
            for rank, each in enumerate(filterd_bm25_results):
                scored_chunks[each["document"]]["score"] += 1 / (K + rank)
            
            sorted_scored_chunks = sorted(scored_chunks.items(), key=lambda item: item[1]["score"], reverse=True)[: int(len(scored_chunks) * 0.7)]
            reordered_chunks = sorted(sorted_scored_chunks, key=lambda item: item[1]["id"], reverse=False)
            all_results.append(str({
                "file": search_params.file_name,
                "relevant_content": "\n".join([each[0] for each in reordered_chunks]),
                "queries": search_params.search_sentences
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
        response = await summary_model.ainvoke(
            [SystemMessage(system_prompt)] + [AIMessage(raw_relevant_contents)] 
        )
        return ToolMessage(
            tool_call_id=tool_call_id, 
            content=response.content, 
            # additional_kwargs=event.model_dump()
        )
    else:
        return ToolMessage(
            tool_call_id=tool_call_id, 
            content="No relevant information found in the uploads", 
            # additional_kwargs=event.model_dump()
        )


file_search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), temperature=0, top_p=0.1).bind_tools([chromadb_search])

async def file_search_agent(state: File_Search_State)->Command[Literal["__end__", "chromadb_search"]]:
    '''
    The purpose of the file_search_agent is for finding the relevant information from the uploaded file chunked and 
    indexed in the chromadb 
    '''
    filenames = []
    for each_message in state["messages"]:
        if isinstance(each_message, HumanMessage) and each_message.additional_kwargs.get("file_names", []):
            filenames += each_message.additional_kwargs.get("file_names")

    system_prompt = "You are the file search agent, according to latest user prompt, the the most relevant information which can help to answer the question."
    if filenames:
        system_prompt += f"\nUser has uploaded files {' '.join(filenames)}. Please use it for file search..."
        "ONLY Search the file content which is belonging to file_search, DONT search on file belong to coding_app"
        "You MUST RESTRICTLY follow routing suggestion from supervisor agent in terms of which file you should search on"

    ###deadloop here
    if state["internal_messages"]:
        message_sequence = state["internal_messages"] + [SystemMessage(content=system_prompt)]
    else:
        message_sequence = state["messages"] + [SystemMessage(content=system_prompt)]

    response = await file_search_model.ainvoke(message_sequence, config={"recursion_limit": 8})

    event = message_event.Event(
        type = "file_search_agent",
        sender = "file_search_agent",
        #content = "Enough Infomration Found.." if not response.tool_calls else "Sending to file search tool for getting more information",
        content = "Enough Infomration Found.." if not response.tool_calls else response.text, 
        input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp = time(),
        message_user = True
    )

    response.additional_kwargs = event.model_dump()
    await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
    if hasattr(response, "tool_calls") and response.tool_calls:
        if state.get("search_round", 0) + 1 > MAX_SEARCH_ATTEMPTS:
            max_search_round_summary = await summary_model.ainvoke(state["internal_messages"] + [HumanMessage(content="As the maxium search reached, summarize the full search result for the next task..")])
            return Command(
                goto="__end__",
                update={
                    "messages": state["messages"] + [HumanMessage(content=f"File serach agent has reached MAXIUM SEARCH ATTEMPTS. Here is the summary: \n{max_search_round_summary}")],
                    "thread_id": state["thread_id"],
                    "sender": "file_search_agent",
                    "search_round": MAX_SEARCH_ATTEMPTS
                }
            )
        return Command(
            goto=response.tool_calls[0].get("name", "__end__"),
            update={
                "internal_messages": message_sequence + [response],
                "sender": "file_search_agent",
                "thread_id": state["thread_id"],
                "pause_required": False,
                "message_user": True,
                "tool_call_id": response.tool_calls[0]['id'],
                "search_round": state.get("search_round", 0) + 1
            }
        )
    else:
        summary = await summary_model.ainvoke(message_sequence + [HumanMessage(content="Now to full search is complete. synthesize all the key search result for the next stage..")])
        return Command(
            goto="__end__",
            update={
                "messages": [AIMessage(content=f"File serach agent has full searched the document. Here is the summary: \n{summary}")],
                "thread_id": state["thread_id"],
                "sender": "file_search_agent"
            }
        )

file_search_app_graph = StateGraph(File_Search_State)
file_search_app_graph.add_node("file_search_agent", file_search_agent)
file_search_app_graph.add_node("chromadb_search", ToolNode([chromadb_search], messages_key="internal_messages"))
file_search_app_graph.add_edge(START, "file_search_agent")
file_search_app_graph.add_edge("chromadb_search", "file_search_agent")
file_search_app = file_search_app_graph.compile()
