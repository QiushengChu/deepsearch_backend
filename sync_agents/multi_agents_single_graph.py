from typing_extensions import Annotated, Sequence, Literal, TypedDict
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage, SystemMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langgraph.types import Command
from langchain_deepseek import ChatDeepSeek
from langchain.tools import tool
from tavily import TavilyClient
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor
from IPython.display import Image, display
import json

load_dotenv()

class GlobalState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str

@tool
def tavily_search(queries: list[str]) -> list[dict]:
    '''
    Search the web using Tavily to find related resource from the Internet
    Args:
        queries(list[str]): summarized search queries
    Return:
        collected research result over the search queries
    '''
    tavily_api_key = os.getenv("tavily_api_key")
    client = TavilyClient(api_key=tavily_api_key)
    with ThreadPoolExecutor(max_workers=5) as executor:
        search_results = list(executor.map(lambda q: client.search(query=q), queries))
    # response = client.search(query=query)
    return search_results

@tool
def user_input(clarify_question: str) -> str:
    '''
    Get user input for clarification
    Args:
        clarify_question(str): the variable is for further clarifying the research topic
    '''
    user_input = input(f"\n{clarify_question}\nPlease give the answer: ")
    return user_input

# Initialize models
search_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).bind_tools([tavily_search])
clarify_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).bind_tools([user_input])
summary_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"))

def clarify_agent(state: GlobalState) -> Command[Literal["clarify_tool", "supervisor"]]:
    """Clarification agent - 总是返回到supervisor"""
    system_prompt = """
    You are a topic clarification agent. Analyze if the query is clear enough for web search. 
    
    CRITICAL INSTRUCTION: If the query is vague, broad, or lacks specific details, you MUST use the user_input tool to ask clarifying questions.
    
    Examples of when to use the tool:
    - Query is too broad (e.g., "AI developments")
    - Missing specific aspects (e.g., time frame, location, specific technology)
    - Need more context about user's intent
    
    Only proceed without tool usage if the query is already specific and clear enough for direct web search.
    """
    messages = state["messages"]
    if len(messages) == 1:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"][0:]
    else:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"][1:]
    response = clarify_model.invoke(all_messages)
    
    if hasattr(response, "tool_calls") and response.tool_calls:
        # Need to ask for clarification
        return Command(
            goto="clarify_tool", 
            update={"messages": [response]}
        )
    else:
        # Query is clear, 返回到supervisor让supervisor决定下一步
        return Command(
            goto="supervisor",
            update={
                "messages": [response],
                "sender": "clarify_agent"
            }
        )

def search_agent(state: GlobalState) -> Command[Literal["tavily_search", "supervisor"]]:
    """Search agent - 总是返回到supervisor"""
    system_prompt = """You are a search agent with access to web search. 
    Use the search tool to find relevant information and summarize the results."""
    messages = state["messages"]
    if len(messages) != 0 and messages[0]:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"][1:]
    else:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"]

    response = search_model.invoke(all_messages)
    
    if hasattr(response, "tool_calls") and response.tool_calls:
        # Need to perform search
        return Command(
            goto="tavily_search",
            update={"messages": all_messages + [response]}
        )
    else:
        # Search completed, 返回到supervisor让supervisor决定下一步
        return Command(
            goto="supervisor",
            update={
                "messages": [response],
                "sender": "search_agent"
            }
        )

def summary_agent(state: GlobalState) -> Command[Literal["supervisor"]]:
    """Summary agent - 总是返回到supervisor"""
    system_prompt = """You are a summary agent. Create a concise report from all search results."""
    messages = state["messages"]
    if len(messages) != 0 and messages[0]:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"][1:]
    else:
        all_messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = summary_model.invoke(all_messages)
    
    return Command(
        goto="supervisor",
        update={
            "messages": [response],
            "sender": "summary_agent"
        }
    )

def topic_summary_agent(state: GlobalState)->Command[Literal["supervisor"]]:
    '''
    This agent is for summerizing user's input with the clarification questions and answers into 3-4 search topic strings
    Return should be a list of string 
    '''
    system_prompt = "Please summarize user's clarification conversation and initial search topic into 3 - 4 search topics for search tool and the output should be [topic1, topic2, ...] in json format"
    response = summary_model.invoke([SystemMessage(content=system_prompt)] + state["messages"])
    print("Here are the search topics:")
    print(response.text)
    return Command(
        goto="supervisor",
        update={
            "messages": [response],
            "sender": "topic_summary_agent"
        }
    )
    

def supervisor(state: GlobalState) -> Command[Literal["clarify_agent", "search_agent", "summary_agent", "topic_summary_agent", "__end__"]]:
    """Supervisor that routes between agents"""
    messages = state["messages"]
    sender = state.get("sender", "")
    
    print(f"Supervisor: current sender = {sender}")
    
    # 初始状态 - 开始clarification
    if not sender or sender == "user":
        return Command(goto="clarify_agent")
    
    # clarify_agent完成后
    elif sender == "clarify_agent":
        last_message = messages[-1]
        # 检查是否还需要继续clarification
        if isinstance(last_message, AIMessage) and not getattr(last_message, 'tool_calls', None):
            # clarification完成，转到topic_summary_agent
            return Command(goto="topic_summary_agent")
        else:
            # 还需要继续clarification
            return Command(goto="clarify_agent")
    elif sender == "topic_summary_agent":
        return Command(goto="search_agent")
    # search_agent完成后
    elif sender == "search_agent":
        last_message = messages[-1]
        # 检查search是否完成
        if isinstance(last_message, AIMessage) and not getattr(last_message, 'tool_calls', None):
            # search完成，转到summary
            return Command(goto="summary_agent")
    
    # summary_agent完成后，结束工作流
    elif sender == "summary_agent":
        return Command(goto="__end__")
    
    # 默认fallback
    return Command(goto="__end__")

# Build the main graph
workflow = StateGraph(GlobalState)

# Add all nodes
workflow.add_node("supervisor", supervisor)
workflow.add_node("clarify_agent", clarify_agent)
workflow.add_node("search_agent", search_agent)
workflow.add_node("summary_agent", summary_agent)
workflow.add_node("topic_summary_agent", topic_summary_agent)
workflow.add_node("clarify_tool", ToolNode([user_input]))
workflow.add_node("tavily_search", ToolNode([tavily_search]))

# Set up edges
workflow.add_edge(START, "supervisor")

# Supervisor routing edges - supervisor决定下一步去哪里
# workflow.add_edge("supervisor", "clarify_agent")
# workflow.add_edge("supervisor", "search_agent")
# workflow.add_edge("supervisor", "summary_agent")
workflow.add_edge("supervisor", "__end__")

# Agent completion edges - 所有agent完成后都返回到supervisor
# workflow.add_edge("clarify_agent", "supervisor")
# workflow.add_edge("search_agent", "supervisor")
# workflow.add_edge("summary_agent", "supervisor")

# Tool execution edges - 工具执行后回到对应的agent
workflow.add_edge("clarify_tool", "clarify_agent")  # user input后回到clarify agent
workflow.add_edge("tavily_search", "search_agent")  # search后回到search agent

# Compile the app
app = workflow.compile()

# Display the graph
display(Image(app.get_graph().draw_mermaid_png()))

# Test function
def run_workflow(user_query: str):
    initial_state = {
        "messages": [HumanMessage(content=user_query)],
        "sender": "user"
    }
    
    print("Starting workflow...")
    # for step in app.stream(initial_state, stream_mode="updates"):
    #     print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    final_state = app.invoke(initial_state)
    print(final_state["messages"][-1].text)


# Test
if __name__ == "__main__":
    result = run_workflow("能帮我看一下47 Darling Street Glebe NSW Sydney这套房子的基本信息以及未来的走势吗？用互联网上的数据做一些合理的预测，比如3年后卖了能价值多少？")