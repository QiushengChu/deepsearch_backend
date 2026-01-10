import os, asyncio
from typing import Sequence, TypedDict, Annotated, Literal
from langgraph.graph import START, StateGraph
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from model.request_models import ROUTE_JSON_SCHEMA
from langchain_deepseek import ChatDeepSeek
from langgraph.types import Command
from model.session_manager import manager
from utils.context import prompt_fetcher_from_cache, prompt_remover_from_cache
# from concurrent.futures import ThreadPoolExecutor
from utils.context import context_purifier
from model import message_event, memory
from time import time
from utils.helper_funcs import summary_fetcher

from model.agents.clarify_app import clarify_app
from model.agents.topic_summary_app import topic_summary_app
from model.agents.search_app import search_app
from model.agents.report_writer_app import report_writer_app
from model.agents.file_search_app import file_search_app
from model.agents.file_generator_app import file_generator_app




load_dotenv()

class Supervisor_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool
    message_user: bool

supervisor_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).with_structured_output(ROUTE_JSON_SCHEMA)
#supervisor_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).with_structured_output(Route)

async def supervisor_agent(state: Supervisor_State, Config=None)->Command[Literal["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "file_generator_app", "__end__"]]:
    '''
    supervise agent is for routing the message states between different sub-agents for completing the deligated tasks.
    '''
    # system_prompt = '''
    # You are a workflow router. Your job is to analyze the current conversation history and route tasks through agents, NOT answer questions.

    # STRICT ROUTING LOGIC:
    # - sender == "user" → Route to "clarify_app" (ONLY when the topic is not clear enough)
    # - sender == "file_search_agent" -> 
    # - sender == "clarify_agent" → Route to "topic_summary_app" (ONLY when the conversation is complex you need to break the conversation into a few topics)
    # - sender == "topic_summary_agent" → Route to "search_app"
    # - sender == "search_agent" → Route to "report_writer_app"
    # - sender == "file_generator_agent" → Route to "file_generator_app"     
    
    # Sub-agent targets:
    # "clarify_agent": if user's request is not clear enough to do the search, clarify agent will be used to clarify research detail with user
    # "topic_summary_agent": based on the previous conversation break conversation down into a few topics and also if previous search topics are sufficient, providing more research topics
    # "search_agent": "based on search topics, using associated search tool for finding relevant information"
    # "report_writer_agent": Report writer is the last step, summarize all the important details with some valid assumption and to write a report or generate a quick answer. Please notice the report writer does not have any tool for file update for search
    # "file_search_agent": if user has file uploaded, there might be relevant content to use
    # "file_generator_app": if user has uploaded file and update the file according to user's prompt. Notice file_generator_app includes content read and extraction function and also file generator function.

    # This is a research question. Please be CRITICAL. Route to "clarify_app" to start the workflow if the question is not clear otherwise you can use search tool to gather real information from the true source.
    # If you think based on the current conversation, the information is sufficient to anwser users' question, you can route to report_writer_agent to answer. 
    # Otherwise, you can route to search agent to get more information.
    # Please ALWAYS return to report_writer_agent for generating answer to user before end the workflow
    # '''

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

    4. "file_search_app" - Searches within uploaded files
    - Use when: user has uploaded files AND question relates to file content
    - Only can search the related information in the uploaded file

    5. "file_generator_app" - Creates/modifies PDF files
    - Use when: user explicitly wants to CREATE, UPDATE, or MODIFY a file
    - CAN: extract file content, generate new PDFs, update existing files
    - Keywords: such as "update my resume", "modify the document", "create a PDF"

    6. "report_writer_app" - Writes text summaries/reports (FINAL STEP)
    - Use when: all information is gathered and ready to present to user
    - CANNOT: generate files, create PDFs, or modify documents
    - ONLY provides text-based responses

    ROUTING LOGIC:
    - If user wants FILE CREATION/MODIFICATION → route to "file_generator_app"
    - If you need some information from the internet or user is asking latest information -> route to "search_app"
    - If user wants some information in the uploaded file → route to "file_search_app"
    - If user wants FINAL ANSWER/REPORT → route to "report_writer_app"

    CRITICAL RULE:
    - report_writer_app NEVER generate a file, if user is asking to generate a file you have to route to file_generator_app for file modification/creation
    - report_writer_app is ONLY for text responses
    - file_generator_app is ONLY for file creation/modification
    - NEVER expect report_writer_app to generate files
    - If user has uploaded any file please include the file_name into the reasoning for a conprehensive reasoning
    '''
    ##    - If previous agent was "file_generator_agent" → route to "report_writer_app" (to summarize results)
    ##if pause_required is True then go to __end__
    if state["pause_required"] == True:
        ##marking the session idle
        manager.update_session(thread_id=state["thread_id"], updates={
            "status": "idle",
            "current_step": "waiting user response",
            "created_at": asyncio.get_event_loop().time(),
            "message_count": len(state["messages"])
        })
        return Command(goto="__end__", update={
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
        PLEASE NOTICE: User has uploaded file(s). Here are the file summaries:
        
        {file_upload_summaries[1]}
        
        If the user's prompt is related to these files, please route to file_search_app.
        PLEASE MENTION the exact file names for searching
        """
        system_prompt += file_upload_prompt


    ##human intervention in case dead loop between supervisor and topic_summary_agent
    if user_prompt_list == []:
        # if state["sender"] == "clarify_agent":
        #     return Command(goto="topic_summary_app", update={
        #         "messages": state["messages"], 
        #         "sender": "supervisor_agent",
        #         "thread_id": state["thread_id"],
        #         "pause_required": False
        #     })
        # elif state["sender"] == "topic_summary_agent":
        #     return Command(goto="search_app", update={
        #         "messages": state["messages"], 
        #         "sender": "supervisor_agent",
        #         "thread_id": state["thread_id"],
        #         "pause_required": False
        #     })
        # elif state["sender"] == "search_agent":
        #     return Command(goto="report_writer_app", update={
        #         "messages": state["messages"],
        #         "sender": "supervisor_agent",
        #         "thread_id": state["thread_id"],
        #         "pause_required": False
        #     })
        # elif state["sender"] == "report_writer_agent":
        #     manager.update_session(thread_id=state["thread_id"], updates={
        #         "status": "idle",
        #         "current_step": "waiting user response",
        #         "created_at": asyncio.get_event_loop().time(),
        #         "message_count": len(state["messages"])
        #     })
        #     return Command(goto="__end__", update={
        #         "messages": state["messages"],
        #         "sender": "supervisor_agent",
        #         "thread_id": state["thread_id"],
        #         "pause_required": False
        #     })
        if state["sender"] == "report_writer_agent":
            manager.update_session(thread_id=state["thread_id"], updates={
                "status": "idle",
                "current_step": "waiting user response",
                "created_at": asyncio.get_event_loop().time(),
                "message_count": len(state["messages"])
            })
            return Command(goto="__end__", update={
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
                timestamp = time()
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
                "messages": state["messages"] + [AIMessage(content=str(response), additional_kwargs={
                    "message_user": True,
                    "message_event": event.model_dump()
                })],
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
            timestamp = time()
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
            timestamp = time()
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
            "messages": merged_state_messages + [AIMessage(content=str(response), additional_kwargs = {"message_user": True, "message_event": event.model_dump()})],
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
supervisor_app_graph.add_node("file_generator_app", file_generator_app)
supervisor_app_graph.add_edge(START, "supervisor_agent")
supervisor_app_graph.add_edge("clarify_app", "supervisor_agent")
supervisor_app_graph.add_edge("topic_summary_app", "supervisor_agent")
supervisor_app_graph.add_edge("search_app", "supervisor_agent")
supervisor_app_graph.add_edge("report_writer_app", "supervisor_agent")
supervisor_app_graph.add_edge("file_search_app", "supervisor_agent")
supervisor_app_graph.add_edge("file_generator_app", "supervisor_agent")



supervisor_app = supervisor_app_graph.compile(checkpointer=memory.checkpointer_manager.initialize())