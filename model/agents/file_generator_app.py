from typing import Annotated, Sequence, Literal, TypedDict
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, SystemMessage, HumanMessage
from langgraph.prebuilt import ToolNode, InjectedState
from langgraph.graph.message import add_messages
from langgraph.graph import START, StateGraph
from langgraph.types import Command
from langchain_core.tools import tool
from utils.helper_funcs import extract_content
from pathlib import Path
from model import message_event
import os, copy
from time import time
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from weasyprint import HTML, CSS
from utils.context import context_purifier


class File_Generator_State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    internal_messages: Annotated[Sequence[BaseMessage], add_messages]
    sender: str
    thread_id: str
    pause_required: bool
    tool_call_id: str


class Pdf_Payload(BaseModel):
    html_body: str = Field(..., description="This is the HTML string format of the file content, the string MUST be working for weasyprint")
    css_styles: str = Field(..., description="THis is the CSS string format of the layout, font and other visual effect for generating the PDF, the string MUST be working for weasyprint")


#pdf_generator_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).with_structured_output(Pdf_Payload)
pdf_generator_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0).with_structured_output(Pdf_Payload)


@tool
async def pdf_generator(
        file_name: str, 
        tool_call_id: Annotated[str, InjectedState("tool_call_id")],
        internal_messages: Annotated[Sequence[BaseMessage], InjectedState("internal_messages")],
        thread_id: Annotated[str, InjectedState("thread_id")]
    ) -> ToolMessage:
    '''
    pdf_generator will take and summarize user's prompt and conversation to make two variables and make an corresponding pdf.
    Args: 
    file_name: the file name of the updated pdf
    internal_messages: it is injected automatically
    '''
    system_prompt = '''
    Please generate two variables according to the file update requirements. The two variables MUST be working with weasyprint as weasyprint is the PDF generator function
    1. html_body(str): it is a string formated of HTML file content   
    2. css_styles(str): it is a string formated css for beatifying the pdf content
    Example:
    html_body = <div class="contact-info"><div class="contact-item"><span class="icon">📱</span> Mobile: [Your Mobile]</div><div class="contact-item"><span class="icon">✉️</span> Email: xxx@com</div></div>
    css-styles = .resume-container { background-color: white; box-shadow: 0 0 15px rgba(0, 0, 0, 0.1); border-radius: 8px; overflow: hidden; padding: 20px;}
    '''
    
    ##purify the internal message status
    clean_messages = context_purifier(internal_messages)
    response = await pdf_generator_model.ainvoke(clean_messages + [SystemMessage(system_prompt)])

    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"></head>
    <body>{response.html_body}</body>
    </html>
    """
    os.makedirs(f"artifactories/{thread_id}", exist_ok=True)
    HTML(string=full_html).write_pdf(
        f"artifactories/{thread_id}/{file_name}",
        stylesheets=[CSS(string=response.css_styles)]
    )
    event = message_event.Event(
        type="pdf_generator has updated pdf",
        sender="pdf_generator_tool",
        content=f"{file_name}",
        input_tokens=getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens=getattr(response, "usage_metadata", {}).get("output_tokens", 0),
        total_tokens=getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp=time()
    )
    return ToolMessage(
        tool_call_id=tool_call_id,
        content=f"{file_name} has been generated into the artifactories",
        additional_kwargs={
            "sender": "pdf_generator_tool",
            "message_user": False,
            "message_event": event.model_dump(),
            "timestamp": time()
        }
    )


@tool
async def content_extractor(
        file_name: str, 
        thread_id: Annotated[str, InjectedState("thread_id")],
        tool_call_id: Annotated[str, InjectedState("tool_call_id")]
    ) -> ToolMessage:
    '''
    This content extractor is extracting content from the targeted files and return a plain string as content
    Args:
        file_name(str): the name of file for content extraction
        thread_id(str): The current session ID (automatically injected)
        tool_call_id(str): The tool call id (automatically injected)
    
    Returns:
        String formate result of the content from the target file 
    '''
    file_path = Path(f"uploads/{thread_id}/{file_name}")
    content = await extract_content(file_path=file_path)
    event = message_event.Event(
        type=f"extracting content from {file_name}",
        sender="content_extractor_tool",
        content=f"extracting content from {file_name}",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        timestamp=time()
    )

    return ToolMessage(
        tool_call_id=tool_call_id,
        content=content,
        additional_kwargs={
            "sender": "content_extractor_tool",
            "message_user": False,
            "message_event": event.model_dump(),
            "timestamp": time()
        }
    )


file_generator_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key"), top_p=0.1, temperature=0).bind_tools([content_extractor, pdf_generator])


async def file_generator_agent(state: File_Generator_State) -> Command:
    """
    File Generator Agent - Document Update Specialist

    Updates and modifies uploaded files based on user requirements while preserving 
    document structure and formatting. Extracts existing content and generates 
    updated versions with requested changes.

    Tools: pdf_generator, content_extractor
    """

    system_prompt = """You are a file generator agent that updates uploaded documents based on user requests.
    Your workflow:
    1. Extract current file content using content_extractor
    2. Analyze user's modification requirements
    3. Generate updated document using pdf_generator

    Key principles:
    - Always read existing content before modifying
    - Maintain document quality and professional appearance  

    You modify existing files, not create new ones. Respect the original document's purpose while incorporating requested updates.
    """
    
    # Manual copy supervisor messages into internal messages state  
    if state["sender"] == "supervisor_agent":
        state["internal_messages"] = copy.deepcopy(state["messages"])

    # Check if we just received a tool response
    last_message = state["internal_messages"][-1]
    
    # If last message is from pdf_generator_tool, we're done
    if isinstance(last_message, ToolMessage) and last_message.additional_kwargs.get("sender") == "pdf_generator_tool":
        event = message_event.Event(
            type=f"PDF file has been generated",
            sender="file_generator_agent",
            content=last_message.content,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            timestamp=time()
        )
        
        final_message = AIMessage(
            content=last_message.content,
            additional_kwargs={
                "sender": "file_generator_agent",
                "message_user": True,
                "message_event": event.model_dump(),
                "timestamp": time()
            }
        )
        
        return Command(
            goto="__end__",
            update={
                "messages": [final_message],
                "sender": "file_generator_agent",
                "pause_required": False
            }
        )

    # Make LLM call with the full internal message history
    print(f"Invoking LLM with {len(state['internal_messages'])} messages")
    response = await file_generator_model.ainvoke(
        list(state["internal_messages"]) + [SystemMessage(content=system_prompt)]
    )
    
    print(f"Response has tool_calls: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")
    
    # Log the response event
    event = message_event.Event(
        type="file_generator_agent response",
        sender="file_generator_agent",
        content=response.content if hasattr(response, 'content') else "",
        input_tokens=getattr(response, "usage_metadata", {}).get("input_tokens", 0),
        output_tokens=getattr(response, "usage_metadata", {}).get("output_tokens", 0),
        total_tokens=getattr(response, "usage_metadata", {}).get("total_tokens", 0),
        timestamp=time()
    )
    
    # Check if there are tool calls
    if hasattr(response, "tool_calls") and response.tool_calls:
        # Route to tool node
        # The response gets added to messages automatically by the graph
        # ToolNode will also add its ToolMessage to messages automatically
        print(f"Routing to tools with tool_call_id: {response.tool_calls[0]['id']}")
        return Command(
            goto="tools",
            update={
                # "messages": [response],  # Add to parent messages
                "messages": state["messages"],  # Add to parent messages
                "internal_messages": [response],  # Add to internal messages  
                "sender": "file_generator_agent",
                "tool_call_id": response.tool_calls[0]['id']
            }
        )
    else:
        # No tool calls, return final response
        final_message = AIMessage(
            content=response.content,
            additional_kwargs={
                "sender": "file_generator_agent",
                "message_user": True,
                "message_event": event.model_dump(),
                "timestamp": time()
            }
        )
        
        return Command(
            goto="__end__",
            update={
                "messages": [final_message],
                "sender": "file_generator_agent",
                "pause_required": False
            }
        )


# Custom tool node that writes to internal_messages
async def custom_tool_node(state: File_Generator_State):
    """Tool node that updates internal_messages instead of messages"""
    # Get the last message which should have tool_calls
    last_message = state["internal_messages"][-1]
    
    # Execute each tool call manually
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]
        
        # Call the appropriate tool
        if tool_name == "content_extractor":
            result = await content_extractor.ainvoke(
                {**tool_args, "thread_id": state["thread_id"], "tool_call_id": tool_call_id}
            )
        elif tool_name == "pdf_generator":
            result = await pdf_generator.ainvoke(
                {
                    **tool_args, 
                    "thread_id": state["thread_id"], 
                    "tool_call_id": tool_call_id,
                    "internal_messages": state["internal_messages"]
                }
            )
        else:
            result = ToolMessage(
                content=f"Unknown tool: {tool_name}",
                tool_call_id=tool_call_id
            )
        
        tool_messages.append(result)
    
    print(f"Tool executed, returning {len(tool_messages)} tool messages")
    return {"internal_messages": tool_messages}


# Build the graph
file_generator_app_graph = StateGraph(File_Generator_State)
file_generator_app_graph.add_node("file_generator_agent", file_generator_agent)
file_generator_app_graph.add_node("tools", custom_tool_node)

file_generator_app_graph.add_edge(START, "file_generator_agent")
file_generator_app_graph.add_edge("tools", "file_generator_agent")

file_generator_app = file_generator_app_graph.compile()