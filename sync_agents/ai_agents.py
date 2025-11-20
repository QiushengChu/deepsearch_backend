from typing_extensions import Annotated, Sequence, Literal, TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from langgraph.graph.message import add_messages
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json


load_dotenv()

content = ""

class EmailEditorAgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    counter: int

@tool
def save_tool(filename: str)->str:
    '''
    this tool is for saving the email content
    Args:
        filename (str): giving a filename as string to specify where to save it 
    Returns:
        EmailEditorAgentState: Confirming that the content has been saved.
    '''
    global content
    with open(filename, "w") as f:
        f.write(content)
    return "Email draft has been saved"

@tool
def update_tool(new_content: str)->str:
    '''
    This is the tool for update the global content string
    Args:
        new_content: the content of the email draft
    Returns:
        the status of the email update
    '''
    global content 
    content = new_content
    print(f"Drafed Email: {content}")
    return "Email updated successfully"

@tool
def send_mail_tool(send_to: str, subject: str, content: str)->str:
    '''
    This send_email function is for sending email to the receipent once people are happy with the email draft
    Args:
        send_to(str): the recepient address
        subject(str): the subject of the email
        content(str): the content of the email body
    '''
    if send_to and subject and content:
        try:
            # Your Gmail credentials
            EMAIL_ADDRESS = "timc19911012@gmail.com"
            EMAIL_PASSWORD = "orvb wdtd zmgm vbrg"  # Must use App Password if 2FA enabled

            # Create email
            msg = MIMEMultipart()
            msg['From'] = EMAIL_ADDRESS
            msg['To'] = send_to
            msg['Subject'] = subject

            body = content
            msg.attach(MIMEText(body, 'plain'))

            # Connect to Gmail SMTP server
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg)

            return f"Email has been sent to {EMAIL_ADDRESS} successfully"
        except Exception as e:
            return "Failed to send email, please check the recepient address"
        
@tool
def balance_checker_tool(name: str)-> dict:
    '''
    This function is for checking the leave balance of a user before sending email, if the balance is not enough, we should make notification to user
    Args:
        name(str): who are we checking balance
    Return:
        the current balance status, current role name 
    '''
    
    with open("balancer_register.json", "r") as f:
        balancer_object = json.load(f)
    target = list(filter(lambda x: x["user"] == name, balancer_object))
    if len(target) > 0:
        target[0]["status"] = "user balance found"
        return target[0]
    else:
        return {"status": "user balance not found, please check your username"}
            

model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).bind_tools([save_tool, update_tool, send_mail_tool, balance_checker_tool])

tools_dict = {
    "save_tool": save_tool,
    "update_tool": update_tool,
    "send_mail_tool": send_mail_tool,
    "balance_checker_tool": balance_checker_tool
}

    

def email_writer(state: EmailEditorAgentState)->Command[Literal["save_tool", "update_tool"]]:
    system_message = SystemMessage(content=f"""
    You are Drafter, a helpful writing assistant. You are going to help the user update and modify documents.
    
    - If the user wants to update or modify content, use the 'update_tool' tool with the complete updated content.
    - If the user wants to save and finish, you need to use the 'save_tool' tool.
    - Make sure to always show the current document state after modifications.
    
    The current document content is:{content}
    """)
    if state["messages"] == None:
        user_prompt = input("\nWhat can I help you today ?")
    else:
        user_prompt = input("\nWhat do you wanna do with this draft ?")
    all_messages = [system_message] + state["messages"] + [HumanMessage(content=user_prompt)] 
    response = model.invoke(all_messages)
    if hasattr(response, "tool_calls"):
        for tool_call in response.tool_calls:
            tool_name = tool_call.get("name")
            # tool_args = tool_call.get("arguments")
            return Command(goto=tool_name, update={"messages": all_messages + [response]})
    return Command(goto="email_writer", update={"messages": all_messages + [response]})

graph = StateGraph(EmailEditorAgentState)
graph.add_node("email_writer", email_writer)
graph.add_node("update_tool", ToolNode([update_tool]))
graph.add_node("save_tool", ToolNode([save_tool]))
graph.add_node("send_mail_tool", ToolNode([send_mail_tool]))
graph.add_node("balance_checker_tool", ToolNode([balance_checker_tool]))
graph.add_edge(START, "email_writer")
graph.add_edge("update_tool", "email_writer")
graph.add_edge("balance_checker_tool", "email_writer")
graph.add_edge("save_tool", END)
graph.add_edge("send_mail_tool", END)

app = graph.compile()


def print_messages(messages):
    if not messages:
        return
    message = messages[-1]
    if isinstance(message, ToolMessage):
        print(f"\nTool Result: {message.content}")
    if isinstance(message, HumanMessage):
        print(f"\nHuman message: {message.content}")
    if isinstance(message, AIMessage):
        print(f"\nAI message: {message.content}")
    
    print(f"\n ======DRAFTED FINISHED========")

def run_document_agent():
    
    state = {"messages": []}
    
    for step in app.stream(state, stream_mode="values"):
        if "messages" in step:
            print_messages(step["messages"])
    


run_document_agent()


