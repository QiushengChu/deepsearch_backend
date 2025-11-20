from typing import Sequence, TypedDict, Annotated, List, Literal
from langgraph.graph import START, StateGraph
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages
from langchain_core.tools import tool
from model.prompt_cache_model import prompt_cache
from model.memory import memory
import asyncio
from model.request_models import Topics, Route, AIClarifyResponse
from langchain_deepseek import ChatDeepSeek
import os
from langgraph.types import Command
from model.session_manager import manager
from langgraph.prebuilt import ToolNode, InjectedState
from utils.context import prompt_fetcher_from_cache, prompt_remover_from_cache
from tavily import AsyncTavilyClient
# from concurrent.futures import ThreadPoolExecutor
from utils.context import conext_purifier
import json

load_dotenv()


class Clarify_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool


topic_clarify_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).with_structured_output(AIClarifyResponse)

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
        "content": "clarify agent is trying to clarify question from user"
    })
    response = await topic_clarify_model.ainvoke(all_messages)
    ai_clarify_str = f"need_to_clarify: {response.need_to_clarify}, clarify_question: {response.clarify_question}"
    if response.need_to_clarify: ##AI needs further clarify with user
        await manager.send_event(thread_id=state["thread_id"], event={
            "type": "hard_pause",
            "sender": "clarify_agent",
            "content": response.clarify_question
    })
        return Command(
            goto="__end__",
            update={"messages": state["messages"] + [AIMessage(content=ai_clarify_str)],
                    "sender": "clarify_agent",
                    "pause_required": True}
        )
    else:
        return Command(goto="__end__", update={
            "messages": state["messages"] + [AIMessage(content=ai_clarify_str)],
            "sender": "clarify_agent",
            "thread_id": state["thread_id"],
            "pause_required": False
        })


class Summary_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    summarized_topics: Sequence[str]
    sender: str
    thread_id: str
    pause_required: bool

##enforce structured output
topic_summary_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Topics)

async def topic_summary_agent(state: Summary_State)-> Command[Literal["__end__"]]:
    '''
    this topic summary agent is responsible for summarizing the the conversation with user's input into 3 - 4 key topics, the topics must contain what user is truely looking for
    '''
    system_prompt = "This is topic summary agent. For summarizing the conversation into 3 - 4 key topics which will be used for other search agent to process. NOTE: the topics must contain what user is truely looking for"

    all_messages = [SystemMessage(content=system_prompt)] + state["messages"]
    converted_messages = conext_purifier(state_messages=all_messages)
    response = await topic_summary_model.ainvoke(converted_messages)
    ## response is already a Topics Oject 
    ai_message = AIMessage(content=response.to_str())
    await manager.send_event(thread_id=state["thread_id"], event={
        "type": "summarize_topics",
        "sender": "topic_summary_agent",
        "content": f"research topic has been summarized into {response.to_str()}"
    })
    return Command(
        goto="__end__",
        update={
            "messages": state["messages"] + [ai_message],
            "summarized_topics": response.topics,
            "sender": "topic_summary_agent",
            "thread_id": state["thread_id"]
        }
    )


class Search_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    search_count: int
    sender: str
    thread_id: str
    tool_call_id: str
    pause_required: bool

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
    links_text = '\n'.join(total_links)
    await manager.send_event(thread_id=thread_id, event={
        "type": "search_event",
        "sender": "search_agent",
        "content": f"found the results from the following links about the breakdown research topics: {links_text}"
    })
    return ToolMessage(
        tool_call_id=tool_call_id, 
        content=json.dumps({"mapped_results": mapped_results}).encode().decode('unicode_escape'), 
        additional_kwargs={
            "max_response_time": max_response_time, 
            "total_num_links": len(total_links), 
            "name": "search_tool", 
            "total_links": total_links
        }
    )

search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).bind_tools([search_tool])
def search_agent(state: Search_State)->Command[Literal["__end__", "search_tool"]]:
    '''This search agent will search the relevant information about the search topics via the search tool I provide'''
    system_prompt = "search agent will be using the search tool for fidning the relevant information from the internet." \
    "for search the information you MUST use the search tool I provide"
    if isinstance(state["messages"][-1], ToolMessage): ##for the tool message returned back from the SearchTool
        return Command(
            goto="__end__",
            update={
                "messages": state["messages"],
                "sender": "search_agent",
                "thread_id": state["thread_id"]
            }
        )
    all_messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = search_model.invoke(all_messages)
    if hasattr(response, "tool_calls") and response.tool_calls:
        return Command(
            goto="search_tool",
            update={
                "messages": all_messages + [response],
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

class Report_Writer_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool

report_writer_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"))

async def report_writer_agent(state: Report_Writer_State)-> Command[Literal["__end__"]]:
    '''
    The report write agent is for summarizing the search results into a small report
    '''
    system_prompt = "You are professional report writer good at summarizing the previous conversation and search result into a formal report. " \
    "Please make sure you can complete the task and DONT add any fake information there, unless it is a educated guess. Please note the information are enough for you to generate a report and generate the report DIRECTLY."

    system_message = SystemMessage(content=system_prompt)
    converted_messages = []
    converted_messages = conext_purifier(state_messages=state["messages"])
    all_messages = [system_message] + converted_messages
    response = await report_writer_model.ainvoke(all_messages)
    print(response.text)
    await manager.send_event(thread_id=state["thread_id"], event={
        "type": "report_writer_event",
        "sender": "report_writer_agent",
        "content": response.text
    })
    return Command(
        goto="__end__",
        update={
            "messages": state["messages"] + [response],
            "sender": "report_writer_agent",
            "thread_id": state["thread_id"]
        }
    )
    

class Supervisor_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool

supervisor_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).with_structured_output(Route)

async def supervisor_agent(state: Supervisor_State, Config=None)->Command[Literal["clarify_app", "topic_summary_app", "search_app", "report_writer_app", "__end__"]]:
    '''
    supervise agent is for routing the message states between different sub-agents for completing the deligated tasks.
    '''
    system_prompt = '''
    You are a workflow router. Your job is to route tasks through agents, NOT answer questions.

    STRICT ROUTING LOGIC:
    - sender == "user" → Route to "clarify_app" (ONLY when the topic is not clear enough)
    - sender == "clarify_agent" → Route to "topic_summary_app" (ONLY when the conversation is complex you need to break the conversation into a few topics)
    - sender == "topic_summary_agent" → Route to "search_app"
    - sender == "search_agent" → Route to "report_writer_app"
    - sender == "reporter_writer_agent" → Route to "__end__"

    This is a research question. Route to "clarify_app" to start the workflow if the question is not clear otherwise you can use search tool to gather real information from the true source.

    DO NOT route to __end__ unless a complete report has been generated.
    '''
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
    ##human intervention in case dead loop between supervisor and topic_summary_agent
    if user_prompt_list == []:
        if state["sender"] == "clarify_agent":
            return Command(goto="topic_summary_app", update={
                "messages": state["messages"], 
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
        elif state["sender"] == "topic_summary_agent":
            return Command(goto="search_app", update={
                "messages": state["messages"], 
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
        elif state["sender"] == "search_agent":
            return Command(goto="report_writer_app", update={
                "messages": state["messages"],
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
        elif state["sender"] == "report_writer_agent":
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
        else: ##default to send to supervisor model to decide the path
            await manager.send_event(thread_id=state["thread_id"], event={
                "type": "supervisor_agent_analyzing",
                "sender": "supervisor_agent",
                "content": "supervisor is analyzing the topics"
            })
            all_messages = [SystemMessage(content=system_prompt)] + state["messages"]
            response = await supervisor_model.ainvoke(conext_purifier(state_messages=all_messages))
            await manager.send_event(thread_id=state["thread_id"], event={
                "type": "supervisor_agent_routing",
                "sender": "supervisor_agent",
                "content": f"Route to {response.path}",
                "reason": response.reasoning
            })

            return Command(goto=response.path, update={
                "messages": state["messages"] + [AIMessage(content=str(response))],
                "sender": "supervisor_agent",
                "thread_id": state["thread_id"],
                "pause_required": False
            })
    else:
        merged_state_messages = state["messages"] + user_prompt_list
        prompt_remover_from_cache(thread_id=state["thread_id"])
        all_messages = [SystemMessage(content=system_prompt)] + merged_state_messages
        await manager.send_event(thread_id=state["thread_id"], event={
            "type": "supervisor_agent_analyzing",
            "sender": "supervisor_agent",
            "content": "supervisor is analyzing the topics"
        })
        
        response = await supervisor_model.ainvoke(conext_purifier(state_messages=all_messages))
        await manager.send_event(thread_id=state["thread_id"], event={
            "type": "supervisor_agent_routing",
            "sender": "supervisor_agent",
            "content": f"Route to {response.path}",
            "reason": response.reasoning
        })
        return Command(goto=response.path, update={
            "messages": all_messages + [AIMessage(content=str(response))],
            "sender": "supervisor_agent",
            "thread_id": state["thread_id"],
            "pause_required": False
        })


clarify_app_graph = StateGraph(Clarify_State)
clarify_app_graph.add_node("clarify_agent", clarify_agent)
clarify_app_graph.add_edge(START, "clarify_agent")
clarify_app = clarify_app_graph.compile()

topic_summary_app_graph = StateGraph(Summary_State)
topic_summary_app_graph.add_node("topic_summary_agent", topic_summary_agent)
topic_summary_app_graph.add_edge(START, "topic_summary_agent")
topic_summary_app = topic_summary_app_graph.compile()


search_app_graph = StateGraph(Search_State)
search_app_graph.add_node("search_agent", search_agent)
search_app_graph.add_node("search_tool", ToolNode([search_tool]))
search_app_graph.add_edge(START, "search_agent")
search_app_graph.add_edge("search_tool", "search_agent")
search_app = search_app_graph.compile()

report_writer_app_graph = StateGraph(Report_Writer_State)
report_writer_app_graph.add_node("report_writer_agent", report_writer_agent)
report_writer_app_graph.add_edge(START, "report_writer_agent")
report_writer_app = report_writer_app_graph.compile()


supervisor_app_graph = StateGraph(Supervisor_State)
supervisor_app_graph.add_node("supervisor_agent", supervisor_agent)
supervisor_app_graph.add_node("clarify_app", clarify_app)
supervisor_app_graph.add_node("topic_summary_app", topic_summary_app)
supervisor_app_graph.add_node("search_app", search_app)
supervisor_app_graph.add_node("report_writer_app", report_writer_app)
supervisor_app_graph.add_edge(START, "supervisor_agent")
supervisor_app_graph.add_edge("clarify_app", "supervisor_agent")
supervisor_app_graph.add_edge("topic_summary_app", "supervisor_agent")
supervisor_app_graph.add_edge("search_app", "supervisor_agent")
supervisor_app_graph.add_edge("report_writer_app", "supervisor_agent")
supervisor_app = supervisor_app_graph.compile(checkpointer=memory)


async def invoke(user_input: str, thread_id: str):
    config = {
        "configurable": { "thread_id": thread_id}
    }
    ##marking the session in progress
    manager.update_session(thread_id=thread_id, updates={
        "status": "in progress",
        "current_step": "in progress",
        "created_at": asyncio.get_event_loop().time(),
        "message_count": manager.get_session(thread_id=thread_id).get("message_count", 0) + 1
    })
    await supervisor_app.ainvoke(
        {
            "messages": [HumanMessage(content=user_input)], 
            "sender": "user", 
            "thread_id": thread_id,
            "pause_required": False
        }, config=config
    )
