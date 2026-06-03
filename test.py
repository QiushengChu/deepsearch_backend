from typing import Annotated, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, StateGraph
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langgraph.types import Command
from pydantic import BaseModel, Field
from langchain.tools import tool
from langgraph.prebuilt import ToolNode
import subprocess
import docker
from docker.errors import ContainerError, ImageNotFound, APIError
import os

load_dotenv()

class AgentForward(BaseModel):
    agent_name: Literal["__end__", "code_planner"] = Field(..., description="The next agent name it can be either __end__ or code_runner")
    reason: str = Field(..., description="the reason of next message forward to the agent")

    @staticmethod
    def to_str(agent_forward: "AgentForward")->str:
        return f"agent_name: {agent_forward.agent_name}, reason: {agent_forward.reason}"

class Plans(BaseModel):
    todo_md: str = Field(..., description="The content for the todo.md file where each task and its progress is explicitly defined.")
    plans: list[str] = Field(..., description="The string list of REMAINING tasks EXCLUDE COMPLETED ones")

class Code(BaseModel):
    code_text: str = Field(..., description="The python code in string")
    file_name: str = Field(..., description="The file name of the code")   

class CodeList(BaseModel):
    code_list: list[Code] = Field(..., description="The list of Code obect. Each of them contains code an file_name of the code") 
    exe_cmd: list[str] = Field(..., description="The list of cmd executions, Notice, python is the runtime exe")

class Problem(BaseModel):
    MAX_RETRIES: int = Field(default=5, description="Maximum number of retries")
    stratch_notepad: str = Field(..., description="Error description of the problem")
    code_fix: CodeList | None = Field(default=None, description="Code fix of the problem")
    

class StateMessage(TypedDict):
    messages: Annotated[BaseMessage, add_messages]
    sub_tasks: list[str] ### task list 
    initial_code: CodeList ### initial code solution
    problems: list[Problem] ## after initial code execution, the array for storing error and corresponding bug fix


supervisor_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(AgentForward)
#supervisor_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key")).with_structured_output(AgentForward)

def supervisor_node(state: StateMessage)->Command[Literal["__end__", "code_planner"]]:
    response = supervisor_model.invoke(state["messages"])
    print(f"The reason of the next forward: {response.reason}")
    return Command(
        goto=response.agent_name,
        update={
            **state,
            "messages": state["messages"] + [AIMessage(content=AgentForward.to_str(response))],
            "sub_tasks": [],
            "initial_code": None,
            "problems": []
        }
    )


code_planner_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Plans)
#code_planner_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key")).with_structured_output(Plans)

def code_planner_node(state: StateMessage)->Command[Literal["code_generator"]]:
    system_prompt = """You are a master project planner for a team of AI coding agents. Your sole responsibility is to take a user's request and create a step-by-step plan in markdown format and subtasks string list. You do **not** write code.
    **Your Workflow:**

    1.  **Analyze the Goal:** Carefully read the user's request and the conversation history to understand the ultimate objective.
    2.  **Formulate a Strategy:** Think about the logical sequence of steps required to achieve the goal.
    3.  **Decompose into Sub-tasks:** Break down your strategy into a list of small, specific, and sequential sub-tasks.

    **Rules for Creating Sub-tasks:**
    *   **Granularity:** Each sub-task must be a single, simple action.
        *   *Bad:* "Process the PDF and extract emails."
        *   *Good:* 1. "Read the text content from the PDF file 'document.pdf'." 2. "Analyze the extracted text to find all email addresses using regex."
    *   **Assume No Context:** The coding agent is stateless. The first sub-task should almost always be to explore the environment (e.g., "List all files in the current directory").
    *   **Be Explicit:** Clearly mention file names or other specific details if they are known.

    **Output Format:**
    Your final output **must** be a markdown-formatted checklist. Start with the header `# Project Plan` and list each sub-task as a checklist item `- [ ]`.

    **Example Output:**
    ```markdown
    # Project Plan

    - [ ] Step 1: List all files in the current directory.
    - [ ] Step 2: Read the content of the PDF file 'document.pdf'.
    - [ ] Step 3: Analyze the extracted text to find all email addresses using a regular expression.
    - [ ] Step 4: Save the found email addresses to a new file named 'emails.txt'.
    """
    system_message = SystemMessage(content=system_prompt)
    response = code_planner_model.invoke(state["messages"] + [system_message])
    ###saving response into todo.md
    with open("./session_123/todo.md", "w") as f:
        f.write(response.todo_md)
    print(f"code planner has saved the plannings into todo.md")
    return Command(
        goto="code_generator",
        update={
            **state,
            "messages": state["messages"] + [AIMessage(content=f"{response.todo_md}")],
            "sub_tasks": response.plans
        }
    )


code_generator_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(CodeList)
#code_generator_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key")).with_structured_output(CodeList)

def code_generator_node(state: StateMessage)->Command[Literal["supervisor", "code_runner"]]:
    if state["sub_tasks"]:
        current_task = state["sub_tasks"][0]
        system_prompt = f"""
        You are a Python coding assistant. Complete the task by calling `code_runner_tool`.
        ### 📌 Task  
        "{current_task}"
        ---
        ### 🛠 Tool Parameters
        - code_list: List of {"file_name": "...", "code_text": "..."} objects. Use [] if no files needed.  
        - exe_cmd: List of shell commands. Runtime: python3.11  
        ---
        ## ⚠️ Critical Rules
        ### 1. Exit Code Convention
        - sys.exit(0) = Task TRULY completed with valid data  
        - sys.exit(1) = Task failed (no data, error, empty result)  
        ---
        ### 2. Always validate before exit(0)
        import sys  
        if not data or len(data) == 0:  
            print("ERROR: No data returned")  
            sys.exit(1)  

        print(result)  
        sys.exit(0)  
        ---

        ## 🚨 IMPORTANT - Bug Fix Rules
        ### ✅ MUST FOLLOW
        - ALWAYS use the EXACT SAME filename when fixing bugs  
        - NEVER add suffixes like _v2, _fixed, _new, _final  
        - NEVER create new files for bug fixes  

        ---
        ### ❌ Wrong Examples

        Original file: script.py  
        - script_v2.py  
        - script_fixed.py  
        - fix_script.py  
        - new_script.py  

        ---
        ### ✅ Correct Example
        Original file: script.py  
        - script.py (overwrite the original)  
        ---
        Another Example  
        Original file: verify_ssl.py  
        - verify_ssl_v2.py  
        - verify_ssl_fixed.py  
        - verify_ssl_final.py  
        - verify_ssl.py  
        ---
        ## 🌐 Environment Constraints
        ### ❌ Not Allowed
        - No API keys available  
        - No custom environment  
        ### ✅ Allowed
        - Public APIs  
        - Local files  
        ---
        ## ⏱ Execution Safety
        - All network requests MUST have timeout=10  
        - No infinite loops  
        - No blocking stdin  
        ---
        ## 🚀 Final Instruction
        Generate code now. Remember: when fixing bugs, use the EXACT SAME filename.
        """
        if state["sub_tasks"]:
            current_task = state["sub_tasks"][0]
            print(f"current_task is {current_task}......")
            if state["problems"]: ## if the problem exists
                ##if there is temp message from stratch_notepad, there is execution error...Regenerating code
                human_prompt = f"""Can you please fix the problem for completing the task {current_task} ? 
                Here is the error history: \n 
                initial code and exe_cmd are \n
                    {state['initial_code'].model_dump_json()}
                following bug fix code and execution is: \n
                    {[ f'No{idx} cmd: {each.model_dump_json()}' for idx, each in enumerate(state['problems'])]}
                Notice: Only print out the KEY informaiton and execution results
                """
                message = HumanMessage(content=human_prompt)
            else:
                message = HumanMessage(content=system_prompt)

            response = code_generator_model.invoke(state["messages"] + [message])
            if isinstance(response, CodeList) and (response.code_list or response.exe_cmd):
                return Command(
                    goto="code_runner",
                    update={
                        **state,
                        "initial_code": state["initial_code"] if state["initial_code"] else response,
                        "problems": [*state['problems'][:-1], state['problems'][-1].model_copy(update={"code_fix": response})] if state["problems"] else []
                    }
                )
    return Command(
        goto="supervisor",
        update={
            "messages": state["messages"] + [response]
        }
    )


def update_todo_md(task: str, output: str)->Plans:
    with open("./session_123/todo.md", "r") as f:
        todo_md = f.read()
    prompt = f"""
    The task {task} has been completed. Can you update the todo.md ? Please mark the completed task with 'x',
    Please review the todo.md and the last step output, update the following steps if necessary (There might be mistakes in the plannings)..
    such as - [x] completed_task
    Here is the content in the todo.md:\n
    {todo_md}\n
    Here is the last step output:\n
    {output}\n
    Notice: 
    Please keep the completed steps the same, ONLY update on the pending tasks if required.
    Also the task which has been completed, Please add some notice or summary for the tasks in terms of results and intermediary code and output files.
    """
    response = code_planner_model.invoke(prompt) ## the output is the PLAN
    with open("./session_123/todo.md", "w") as f:
        f.write(response.todo_md)
    print(f"todo.md has been updated....")
    return response
    

def code_runner_node(state: StateMessage) -> Command[Literal["code_generator"]]:
    '''
    This function is for saving the code into the code file and running the code in the sandbox environment
    return result of execution
    '''
    code_list = state["problems"][-1].code_fix if state["problems"] else state["initial_code"]
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": f"^session_123"})
        for code in code_list.code_list:
            with open(f"./session_123/{code.file_name}", "w") as f:
                f.write(code.code_text)
        if not containers:
            ##if container does not exist
            host_path = os.path.abspath("./session_123")
            client.containers.run(
                image="python:3.11.15-trixie",
                name="session_123",
                volumes={
                    host_path: {'bind': '/usr/src/app', 'mode': 'rw'}
                },
                command="tail -f /dev/null",
                detach=True
            )
        else:
            ## if the container is dead
            if containers[0].status != "running":
                ##resume 
                containers[0].start()

        results = []
        for cmd in code_list.exe_cmd:
            exit_code, output = containers[0].exec_run(
                cmd,
                workdir="/usr/src/app"
            )
            if exit_code != 0:
                result = f"cmd: {cmd} execution failed due to {output.decode('utf-8').strip()}"
                return Command(
                    goto="code_generator",
                    update={ 
                        **state, 
                        "problems": [*state["problems"], Problem(MAX_RETRIES=5, stratch_notepad=result, code_fix=None)]
                    }
                )
            results.append(f"The execution result of {cmd} is {output.decode('utf-8').strip()}")

        ## update the todo.md after the successful execution
        plans = update_todo_md(task=state["sub_tasks"][0], output="\n".join(results))
        return Command(
            goto="code_generator",
            update={ 
                **state, 
                "initial_code": None, 
                "problems": [], 
                "sub_tasks": plans.plans,
                "messages": state["messages"] + [AIMessage(content=code_list.model_dump_json()), HumanMessage(content="\n".join(results))]
            }
        )
    except Exception as e:
        return Command(
            goto="code_generator",
            update={ **state, "problems": state["problems"].append(Problem(MAX_RETRIES=5, stratch_notepad=result, code_fix=[]))}
        )


supervisor_app_graph = StateGraph(StateMessage)
supervisor_app_graph.add_node("supervisor", supervisor_node)
supervisor_app_graph.add_node("code_planner", code_planner_node)
supervisor_app_graph.add_node("code_generator", code_generator_node)
supervisor_app_graph.add_node("code_runner", code_runner_node)
# supervisor_app_graph.add_node("code_runner_tool", ToolNode(tools=[code_runner_tool]))
supervisor_app_graph.add_edge(START, "supervisor")
# supervisor_app_graph.add_edge("code_runner_tool", "code_executor")
app = supervisor_app_graph.compile()

h_message = HumanMessage(content="""能帮我产生一个fastapi的代码吗？ 我需要listen在8000，用ssl进行加密通信，有一个Get /hello 然后返回hello world，代码必须能跑""")
app.invoke({"messages": [h_message]})