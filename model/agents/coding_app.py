from typing import Annotated, TypedDict, Literal, Sequence
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, StateGraph
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import BaseModel, Field
import os, asyncio
from utils.helper_funcs import run_docker_commands
from docker.errors import ContainerError, ImageNotFound, APIError
from model.code_app_models import AgentForward, Plans, CodeList, Problem, Todo


load_dotenv()


class StateMessage(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    internal_messages: Annotated[Sequence[BaseMessage], add_messages]
    tasks: list[str]
    current_task_id: int
    initial_code: CodeList
    problems: list[Problem]
    sender: str
    thread_id: str
    coding_task_complete: bool
    pause_required: bool

agent_forward_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(AgentForward)

async def agent_forward_node(state: StateMessage)->Command[Literal["__end__", "code_planner"]]:
    '''
    entrance of the code agent, forward to code planer if internal message is empty
    '''
    
    if state.get("coding_task_complete", False):
        system_prompt = "As the coding task completed, specify either output_obj_path or output_result for the supervisor agent to send to user.."
        response = await agent_forward_model.ainvoke(state["internal_messages"] + [SystemMessage(content=system_prompt)])
        if response.output_result:
            response.task_complete_summary += f"\nOutput result: {response.output_result}"
        if response.output_obj_path:
            response.task_complete_summary += f"\nOutput Object Path: {response.output_obj_path}"
        with open(f"coding_space/{state['thread_id']}/todo.md", "r") as f:
            todo_md = f.read()
        return Command(
            goto="__end__",
            update={
                **state,
                "messages": state["messages"] + [AIMessage(content=f"{response.task_complete_summary if response.task_complete_summary else 'The coding task has been completed.'} \n This is todo.md for reference\n {todo_md}")]
            }
        )
    else:
        ## coding task is not complete
        system_prompt = """Based on the conversation, extract and summarize the user's coding task requirements in detail.
        Include ALL of the following if mentioned:
        - **Goal**: What the user wants to achieve
        - **User-provided data**: Any personal info, content, or data the user has given (e.g. name, resume content, dataset values)
        - **Output**: Expected output format, file name, file path (e.g. output.pdf, report.csv)
        - **Constraints**: Any specific requirements (e.g. libraries to use, style, language)

        Be specific. Do NOT generalize or paraphrase user's data - preserve the exact details provided. It will be used for the further agent to generate code.
        """
        response = await agent_forward_model.ainvoke(state["messages"] + [SystemMessage(content=system_prompt)])
        os.makedirs(name=f"coding_space/{state['thread_id']}", exist_ok=True)
        return Command(
            goto="code_planner",
            update={
                **state,
                "coding_task_complete": False, ## even route to __end__, set complete to False
                "internal_messages": state["internal_messages"] + [AIMessage(content=response.spec)],
                "tasks": []
            }
        )


    
code_planner_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Plans)

async def code_planner_node(state: StateMessage)->Command[Literal["code_generator"]]:
    '''
    creating code plan
    '''
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
    *   **Minimal Change:** Make sure each step will be very inclusive because the user might be asking for updating on existing code (Updating on the existing code will be more suitable via cli tool such as sed, awk etc)

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
    response = await code_planner_model.ainvoke(state["internal_messages"] + [SystemMessage(content=system_prompt)])

    with open(f"coding_space/{state['thread_id']}/todo.md", "w") as f:
        f.write(response.todo_md)
    return Command(
        goto="code_generator",
        update={
            **state,
            "internal_messages": state["internal_messages"] + [AIMessage(content=response.todo_md)],
            "tasks": response.plans,
            "current_task_id": 0
        }
    )


code_generator_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(CodeList)

async def code_generator_node(state: StateMessage)->Command[Literal["agent_forward", "code_runner"]]:
    if state["current_task_id"] < len(state['tasks']):
        ## still having task to do
        current_task = state["sub_tasks"][0]
        system_prompt = f"""
        You are a Python coding assistant. Complete the task by calling `code_runner_tool`.
        ### 📌 Task  
        "{current_task}"
        ---
        ### 🛠 Tool Parameters
        - code_list: List of {{"file_name": "...", "code_text": "..." objects}}. Use [] if no files needed.  
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
        - ALWAYS overwrite ORGINAL files even bug fix, NO versioning on the file name
        ---
        ### ❌ Wrong Examples

        Original file: script.py  
        - script_v2.py  
        - script_fixed.py  

        ---
        ### ✅ Correct Example
        Original file: script.py  
        - script.py (overwrite the original)  
        ---
        ## 🌐 Environment Constraints
        - There is no ANY API_KEY in environmental variable

        ## ⏱ Execution Safety
        - All network requests MUST have timeout=10  
        - No infinite loops  
        - No blocking stdin  
        ---
        ## 🚀 Final Instruction
        If you can use system commands such as ls, cat, AVOIDING writing code to do the same. 
        But if there is a need to write a script into a file to handle some complex logic, write into file and use cmd to run it via python xxx.py.
        You can use pip install $dependency_package for dependency installation
        """
        #print(f"current_task is {current_task}")
        if state.get("problems", None): 
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
        response = await code_generator_model.ainvoke(state["internal_messages"] + [message])
        if isinstance(response, CodeList) and (response.code_list or response.exe_cmd):
            return Command(
                goto="code_runner",
                update={
                    **state,
                    "internal_messages": state["internal_messages"] + [message],
                    "initial_code": state["initial_code"] if state.get("initial_code", None) else response,
                    "problems":  [*state["problems"][:-1],  state["problems"][-1].model_copy(update={"code_fix": response})] if state.get("problems", []) else []
                }
            )
    else:
        return Command(
            goto="agent_forward",
            update={
                **state,
                "coding_task_complete": True
            }
        )

todo_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Todo)

async def update_todo_md(*, task: str, output: str, thread_id: str)->Plans:
    with open(f"coding_space/{thread_id}/todo.md", "r") as f:
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
    response = await todo_model.ainvoke(prompt)
    with open(f"coding_space/{thread_id}/todo.md", "w") as f:
        f.write(response.todo_md)
    print(f"todo.md has been updated")
    return response

async def code_runner_node(state: StateMessage)->Command[Literal["code_generator"]]:
    '''
    This function is for saving the code into the code file and running the code in the sandbox environment
    return result of execution
    '''
    codes: CodeList = state["problems"][-1].code_fix if state["problems"] else state["initial_code"]
    result_tuple = await asyncio.to_thread(lambda: run_docker_commands(thread_id=state["thread_id"], exe_cmds=codes.exe_cmd, code_files=codes.code_list))
    if result_tuple[0]: ##(bool, result(str))
        ##if there is no error after running all commands
        await update_todo_md(task=state["sub_tasks"][0], output=result_tuple[1], thread_id=state["thread_id"])
        return Command(
            goto="code_generator",
            update={
                **state,
                "problems": [],
                "initial_code": None,
                "current_task_id": state["current_task_id"] + 1,
                "internal_messages": state["internal_messages"] + [AIMessage(content=codes.model_dump_json()), HumanMessage(content=result_tuple[1])]
            }
        )
    else:
        return Command(
            goto="code_generator",
            update={
                **state,
                "problems": [*state["problems"], Problem(stratch_notepad=result_tuple[1], code_fix=None)]
            }
        )



coding_app_graph = StateGraph(StateMessage)
coding_app_graph.add_node("agent_forward", agent_forward_node)
coding_app_graph.add_node("code_planner", code_planner_node)
coding_app_graph.add_node("code_generator", code_generator_node)
coding_app_graph.add_node("code_runner", code_runner_node)
coding_app_graph.add_edge(START, "agent_forward")
coding_app = coding_app_graph.compile()


