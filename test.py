import operator
from typing import Sequence, Annotated, Literal, TypedDict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import add_messages
from langgraph.types import Command, Overwrite

## --- 1. 状态定义 ---

# 统一使用 add_messages 作为归约器
class ChatStateMessage(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str

# 子图状态也使用相同的归约器
class SummaryStateMessage(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # 改为 add_messages
    sender: str

## --- 2. Agent / Node 定义 ---

def chat_agent(state: ChatStateMessage) -> Command[Literal["__end__", "summary_app"]]:
    """主 Agent，负责添加消息和结束流程"""

    if state["sender"] == "summary_agent":
        print("✅ [Chat Agent] 收到 Summary Agent 的回复，流程结束。")
        print(f"Final Messages in Chat: {[msg.content for msg in state['messages']]}")
        return Command(
            goto=END,
            update={
                "sender": "chat_agent",
            }
        )
        
    print(f"\n--- 🏃 CHAT AGENT RUNNING (Sender: {state['sender']}) ---")
    print(f"Current Messages: {[msg.content for msg in state['messages']]}")
    
    # 第一次运行时添加消息
    message_list = ["adding message A", "adding message B"]
    response_messages = [AIMessage(content=each) for each in message_list]
    
    return Command(
        goto="summary_app",
        update={
            "sender": "chat_agent",
            "messages": response_messages 
        }
    )

def summary_agent(state: SummaryStateMessage) -> Command[Literal["__end__"]]:
    """Summary Agent，使用 Command 返回 Overwrite"""
    print(f"\n--- 📝 SUMMARY AGENT RUNNING ---")
    print(f"Incoming Messages: {[msg.content for msg in state['messages']]}")
    
    summary_message = AIMessage(content="This is the summarized and final message.")
    
    # 关键修改：使用 Command 返回 Overwrite
    return Command(
        update={
            "sender": "summary_agent",
            "messages": Overwrite([summary_message])
        }
    )

## --- 3. 构建子图 (Summary App) ---

summary_app_graph = StateGraph(SummaryStateMessage)
summary_app_graph.add_node("summary_agent", summary_agent)

# 使用 Command 机制，直接连接到 END
summary_app_graph.add_edge(START, "summary_agent")
summary_app_graph.add_edge("summary_agent", END)

summary_app = summary_app_graph.compile()

## --- 4. 构建主图 (Chat App) ---

chat_app_graph = StateGraph(ChatStateMessage)
chat_app_graph.add_node("chat_agent", chat_agent)
chat_app_graph.add_node("summary_app", summary_app)

chat_app_graph.add_edge(START, "chat_agent")
chat_app_graph.add_edge("summary_app", "chat_agent")

chat_app = chat_app_graph.compile()

## --- 5. 执行 ---

initial_state = {
    "messages": [HumanMessage(content="This is the first user message.")],
    "sender": "user"
}

print("--- 🚀 开始执行 LangGraph 流程 ---")
result = chat_app.invoke(initial_state)
print("--- 🏁 流程执行完毕 ---")

print("\n--- 结果验证 ---")
print(f"最终 messages 列表长度: {len(result['messages'])}")
print(f"最终 messages 内容: {[msg.content for msg in result['messages']]}")

# from langgraph.graph import StateGraph, START, END
# from langgraph.types import Overwrite
# from typing_extensions import Annotated, TypedDict
# import operator

# class State(TypedDict):
#     messages: Annotated[list, operator.add]

# def add_message(state: State):
#     return {"messages": ["first message"]}

# def replace_messages(state: State):
#     # Bypass the reducer and replace the entire messages list
#     return {"messages": Overwrite(["replacement message"])}

# builder = StateGraph(State)
# builder.add_node("add_message", add_message)
# builder.add_node("replace_messages", replace_messages)
# builder.add_edge(START, "add_message")
# builder.add_edge("add_message", "replace_messages")
# builder.add_edge("replace_messages", END)

# graph = builder.compile()

# result = graph.invoke({"messages": ["initial"]})
# print(result["messages"])