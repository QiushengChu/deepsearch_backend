import os, asyncio
from typing import Sequence, TypedDict, Annotated, Literal
from langgraph.graph import START, StateGraph
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from model.request_models import ROUTE_JSON_SCHEMA, Route
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from model.session_manager import manager
from utils.context import prompt_fetcher_from_cache, prompt_remover_from_cache
# from concurrent.futures import ThreadPoolExecutor
from utils.context import context_purifier
from model import message_event, memory
from time import time
from utils.helper_funcs import summary_fetcher, get_uploaded_file_from_session

from model.agents.clarify_app import clarify_app
from model.agents.topic_summary_app import topic_summary_app
from model.agents.search_app import search_app
from model.agents.report_writer_app import report_writer_app
from model.agents.file_search_app import file_search_app
from model.agents.coding_app import coding_app




load_dotenv()

class Supervisor_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages] ##for context and further context optimization
    ui_messages: Annotated[Sequence[BaseMessage], add_messages] ##for ui visualization and message backtrack
    sender: str
    thread_id: str
    pause_required: bool
    message_user: bool

supervisor_model = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=os.getenv("api_key"), 
    top_p=0.1, temperature=0, 
    extra_body={"thinking": {"type": "disabled"}}
).with_structured_output(ROUTE_JSON_SCHEMA)
#supervisor_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).with_structured_output(ROUTE_JSON_SCHEMA)

async def supervisor_agent(
    state: Supervisor_State, 
    Config=None
)->Command[Literal["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "coding_app", "__end__"]]:
    '''
    supervise agent is for routing the message states between different sub-agents for completing the deligated tasks.
    '''
    system_prompt = '''
    You are a workflow router. Your job is to analyze the current conversation history and route tasks through agents, NOT answer questions.

    AGENT CAPABILITIES (IMPORTANT):

    1. "clarify_app" - Clarifies unclear user requests
    - Use when: user's question is ambiguous or needs more detail
    - Only when user's requirement is not clear

    2. "topic_summary_app" - Breaks down complex topics
    - Use when: complex research needs to be split into subtopics

    3. "search_app" - Searches for information online
    - Use when: need to gather real information from external sources
    - Cannot: generate files or write reports

    4. 'coding_app'
    - Use ONLY when: The file contains source code, OR the task requires writing Python code to process, parse, compute, or manipulate the file data (e.g., text processing, calculations, structured extraction).

    5. 'file_search_app'
    - Use ONLY when: The file has been pre-digested/indexed, AND the user's goal is to lookup, search, or locate specific background facts or information inside text-heavy documents (e.g., PDFs, Docx).
    - DO NOT USE if the file requires computational analysis, data extraction via script, or code execution.

    6. "report_writer_app" - Writes text summaries/reports (FINAL STEP)
    - Use when: all information is gathered and ready to present to user
    - CANNOT: generate files, create PDFs, or modify documents
    - ONLY provides text-based responses

    ROUTING LOGIC:
    - If the problem can be solved by coding -> route to "coding_app"
    - If you need some information from the internet or user is asking latest information -> route to "search_app"
    - If user wants some information in the uploaded file → route to "file_search_app"
    - If user wants FINAL ANSWER/REPORT → route to "report_writer_app"

    CRITICAL RULE:
    - report_writer_app is ONLY for text responses, NEVER expect report_writer_app to generate files
    - NEVER route file supposed to be processed by coding agent to file search agent, vice versa
    - If coding_app just completed the coding task, DONT route back to it as a infinite dead loop, unless the coding task failed.
    - CRISTALLY CLEAR about the sub agent should do, including task, goal, coding/file and other type of objects.
    '''
    ##    - If previous agent was "file_generator_agent" → route to "report_writer_app" (to summarize results)
    ##if pause_required is True then go to __end__
    uploaded_files = get_uploaded_file_from_session(session_id=state["thread_id"]) ##return str or None
        
    if state["pause_required"] == True:
        ##marking the session idle
        manager.update_session(thread_id=state["thread_id"], updates={
            "status": "idle",
            "current_step": "waiting user response",
            "created_at": asyncio.get_event_loop().time(),
            "message_count": len(state["messages"])
        })
        return Command(goto="__end__", update={
                "ui_messages": state["ui_messages"],
                "messages": state["messages"],
                "sender": state["sender"],
                "thread_id": state["thread_id"],
                "pause_required": True
            }
        )
    
    ##if there is user_prompt in prompt_cache need to rerun the context
    user_prompt_list = prompt_fetcher_from_cache(thread_id=state["thread_id"])
    ## check if the current session has file upload summaries
    file_upload_summaries = await summary_fetcher(session_id=state["thread_id"])
    if file_upload_summaries[0]: ##if exists
        file_upload_prompt = f"""
        PLEASE NOTICE: User has uploaded file(s). 
        {uploaded_files}
        Here are the file summaries:
        {file_upload_summaries[1]}
        IMPORTANT:
        The agent for processing specific typed file has been mentioned above. EXACTLY following it
        If the prompt requires understanding the files with both process_method, you have to route to both 'file_search_app' and then 'coding_app' for complete process
        """
        system_prompt += file_upload_prompt
    elif user_prompt_list is not None:
        file_upload_prompt = f"""
        PLEASE NOTICE: User has uploaded file(s). 
        {uploaded_files}
        IMPORTANT:
        The agent for processing specific typed file has been mentioned above. EXACTLY following it
        If the prompt requires understanding the files with both process_method, you have to route to both 'file_search_app' and then 'coding_app' for complete process
        """
        system_prompt += file_upload_prompt
    else:
        system_prompt
        


    ##human intervention in case dead loop between supervisor and topic_summary_agent
    if user_prompt_list == []:
        if state["sender"] == "report_writer_agent":
            manager.update_session(thread_id=state["thread_id"], updates={
                "status": "idle",
                "current_step": "waiting user response",
                "created_at": asyncio.get_event_loop().time(),
                "message_count": len(state["messages"])
            })
            return Command(goto="__end__", update={
                "ui_messages": state["ui_messages"],
                "messages": state["messages"],
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
        else: ##default to send to supervisor model to decide the path as sender is user
            event = message_event.Event(
                type = "supervisor_agent_analyzing",
                sender = "supervisor_agent",
                content = "supervisor is analyzing the topics",
                message_user = True,
                input_tokens = 0,
                output_tokens = 0,
                total_tokens = 0,
                timestamp = time()
            )
            await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
            all_messages = state["messages"] + [SystemMessage(content=system_prompt)]
            response = await supervisor_model.ainvoke(context_purifier(state_messages=all_messages))
            event = message_event.Event(
                type = "supervisor_agent_routing",
                sender = "supervisor_agent",
                content = f"Route to {response['path']}, because {response['reasoning']}",
                input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
                output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
                total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
                timestamp = time(),
                message_user = True 
            )
            await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
            if response['path'] == "__end__":
                manager.update_session(thread_id=state["thread_id"], updates={
                    "status": "idle",
                    "current_step": "waiting user response",
                    "created_at": asyncio.get_event_loop().time(),
                    "message_count": len(state["messages"])
                })

            return Command(goto=response['path'], update={
                "messages": [SystemMessage(content=system_prompt), AIMessage(content=str(response), additional_kwargs=event.model_dump())],
                "ui_messages": state["ui_messages"],
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
    else:
        merged_state_messages = state["messages"] + user_prompt_list
        prompt_remover_from_cache(thread_id=state["thread_id"])
        all_messages = merged_state_messages + [SystemMessage(content=system_prompt)]
        event = message_event.Event(
            type = "supervisor_agent_analyzing",
            sender = "supervisor_agent",
            content = "supervisor is analyzing the topics",
            input_tokens = 0,
            output_tokens = 0,
            total_tokens = 0,
            timestamp = time(),
            message_user = True
        )
        await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
        
        response = await supervisor_model.ainvoke(context_purifier(state_messages=all_messages))
        event = message_event.Event(
            type = "supervisor_agent_routing",
            sender = "supervisor_agent",
            content = f"Route to {response['path']}, because {response['reasoning']}",
            input_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
            output_tokens = getattr(response, "usage_metadata", {}).get("input_tokens", 0),
            total_tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0),
            timestamp = time(),
            message_user = True
        )
        await manager.send_event(thread_id=state["thread_id"], event=event.model_dump())
        if response['path'] == "__end__":
            manager.update_session(thread_id=state["thread_id"], updates={
                "status": "idle",
                "current_step": "waiting user response",
                "created_at": asyncio.get_event_loop().time(),
                "message_count": len(state["messages"])
            })
        return Command(goto=response['path'], update={
            "messages": user_prompt_list + [AIMessage(content=str(response), additional_kwargs = event.model_dump())],
            "ui_messages": [AIMessage(content=str(response))],
            "sender": "supervisor_agent",
            "thread_id": state["thread_id"],
            "pause_required": False
        })


supervisor_app_graph = StateGraph(Supervisor_State)
supervisor_app_graph.add_node("supervisor_agent", supervisor_agent)
# supervisor_app_graph.add_node("search_summary_node", search_summary_node)
supervisor_app_graph.add_node("clarify_app", clarify_app)
supervisor_app_graph.add_node("topic_summary_app", topic_summary_app)
supervisor_app_graph.add_node("search_app", search_app)
supervisor_app_graph.add_node("report_writer_app", report_writer_app)
supervisor_app_graph.add_node("file_search_app", file_search_app)
# supervisor_app_graph.add_node("file_generator_app", file_generator_app)
supervisor_app_graph.add_node("coding_app", coding_app)
supervisor_app_graph.add_edge(START, "supervisor_agent")
supervisor_app_graph.add_edge("clarify_app", "supervisor_agent")
supervisor_app_graph.add_edge("topic_summary_app", "supervisor_agent")
supervisor_app_graph.add_edge("search_app", "supervisor_agent")
supervisor_app_graph.add_edge("report_writer_app", "supervisor_agent")
supervisor_app_graph.add_edge("file_search_app", "supervisor_agent")
# supervisor_app_graph.add_edge("file_generator_app", "supervisor_agent")
supervisor_app_graph.add_edge("coding_app", "supervisor_agent")



supervisor_app = supervisor_app_graph.compile(checkpointer=memory.checkpointer_manager.initialize())