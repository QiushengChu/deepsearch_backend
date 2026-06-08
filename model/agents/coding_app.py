from typing import Annotated, TypedDict, Literal, Sequence
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, StateGraph
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError
import os, asyncio
from utils.helper_funcs import run_docker_commands, safely_ainvoke
from docker.errors import ContainerError, ImageNotFound, APIError
from model.code_app_models import AgentForward, Plans, CodeList, Problem, Todo


load_dotenv()


class StateMessage(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    internal_messages: Annotated[Sequence[BaseMessage], add_messages]
    steps: list[str]
    current_step_id: int
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

        response_tuple = await safely_ainvoke(model=agent_forward_model, message_sequence=state["internal_messages"] + [SystemMessage(content=system_prompt)])
        if not response_tuple[0]: ## if exception 
            return Command(
                goto="agent_forward",
                update={
                    **state,
                    "internal_messages": state["internal_messages"] +[SystemMessage(content=system_prompt)] + [HumanMessage(content=response_tuple[1])] ## attach exception message
                }
            )
        response = response_tuple[1]
        summary = response.task_complete_summary or "The coding task has been completed."
        if response.output_result:
            summary += f"\nOutput result: {response.output_result}"
        if response.output_obj_path:
            summary += f"\nOutput Object Path: {response.output_obj_path}"
        with open(f"coding_space/{state['thread_id']}/todo.md", "r") as f:
            todo_md = f.read()
        return Command(
            goto="__end__",
            update={
                **state,
                "messages": state["messages"] + [AIMessage(content="From coding_app: " + f"{response.task_complete_summary if response.task_complete_summary else 'The coding task has been completed.'} \n This is todo.md for reference\n {todo_md}")],
                "sender": "coding_app"
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
        message_sequence = state["messages"] + [SystemMessage(content=system_prompt)]
        response_tuple = await safely_ainvoke(model=agent_forward_model, message_sequence=message_sequence)
        if not response_tuple[0]:##exception happen
            return Command(
                goto="agent_forward",
                update={
                    **state,
                    "internal_messages": message_sequence + [HumanMessage(content=response_tuple[1])] ## attach exception message
                }
            )
        response = response_tuple[1]
        # response = await agent_forward_model.ainvoke(state["messages"] + [SystemMessage(content=system_prompt)])
        os.makedirs(name=f"coding_space/{state['thread_id']}", exist_ok=True)
        return Command(
            goto="code_planner",
            update={
                **state,
                "coding_task_complete": False, ## even route to __end__, set complete to False
                "internal_messages": state["internal_messages"] + [AIMessage(content=response.spec)],
                "steps": []
            }
        )


    
code_planner_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(Plans)

async def code_planner_node(state: StateMessage)->Command[Literal["code_generator"]]:
    '''
    creating code plan
    '''
    system_prompt = """You are a master project planner for a team of AI coding agents. Your sole responsibility is to take a user's request and create a step-by-step plan in markdown format and steps string list. You do **not** write code.
    **Your Workflow:**

    1.  **Analyze the Goal:** Carefully read the user's request and the conversation history to understand the ultimate objective.
    2.  **Formulate a Strategy:** Think about the logical sequence of steps required to achieve the goal.
    3.  **Decompose into steps:** Break down your strategy into a list of small, specific, and sequential steps.

    **Rules for Creating steps:**
    *   **Granularity:** Each step must be a single, simple action.
        *   *Bad:* "Process the PDF and extract emails."
        *   *Good:* 1. "Read the text content from the PDF file 'document.pdf'." 2. "Analyze the extracted text to find all email addresses using regex."
    *   **Assume No Context:** The coding agent is stateless. The first step should almost always be to explore the environment (e.g., "List all files in the current directory").
    *   **Be Explicit:** Clearly mention file names or other specific details if they are known.
    *   **Minimal Change:** Make sure each step will be very inclusive because the user might be asking for updating on existing code (Updating on the existing code will be more suitable via cli tool such as sed, awk etc)

    **Output Format:**
    Your final output **must** be a markdown-formatted checklist. Start with the header `# Project Plan` and list each step as a checklist item `- [ ]`.

    **Example Output:**
    ```markdown
    # Project Plan

    - [ ] Step 1: List all files in the current directory.
    - [ ] Step 2: Read the content of the PDF file 'document.pdf'.
    - [ ] Step 3: Analyze the extracted text to find all email addresses using a regular expression.
    - [ ] Step 4: Save the found email addresses to a new file named 'emails.txt'.
    But make each step into a sperate string list
    """
    message_sequence = state["internal_messages"] + [SystemMessage(content=system_prompt)]
    response_tuple = await safely_ainvoke(model=code_planner_model, message_sequence=message_sequence)
    # response = await code_planner_model.ainvoke(state["internal_messages"] + [SystemMessage(content=system_prompt)])
    if not response_tuple[0]:
        return Command(
            goto="code_planner",
            update={
                **state,
                "internal_messages": message_sequence + [HumanMessage(content=response_tuple[1])] ## attach exception message
            }
        )
    response = response_tuple[1]
    with open(f"coding_space/{state['thread_id']}/todo.md", "w") as f:
        f.write("\n".join(response.steps))
    return Command(
        goto="code_generator",
        update={
            **state,
            "internal_messages": state["internal_messages"] + [AIMessage(content="\n".join(response.steps))],
            "steps": response.steps,
            "current_step_id": 0
        }
    )


code_generator_model = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("api_key")).with_structured_output(CodeList)

async def code_generator_node(state: StateMessage)->Command[Literal["agent_forward", "code_runner"]]:
    if state["current_step_id"] < len(state['steps']):
        ## still having steps to do
        current_step = state["steps"][state["current_step_id"]]
        system_prompt = f"""
        You are a Python coding assistant. Complete the step by calling `code_runner_tool`.
        ### 📌 Step  
        "{current_step}"
        ---
        ### 🛠 Tool Parameters
        - code_list: List of {{"file_name": "...", "code_text": "..." objects}}. Use [] if no files needed.  
        - exe_cmd: List of shell commands. Runtime: python3.11  
        ---
        ## ⚠️ Critical Rules
        ### 1. Exit Code Convention
        - sys.exit(0) = Step TRULY completed with valid data  
        - sys.exit(1) = Step failed (no data, error, empty result)  
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

        if state.get("problems", None): 
            ## initial code might be None, when pydantic validation error 
            human_prompt = f"""
            ## 🐛 Bug Fix Request
            ### 📌 Current Step
            {state['steps'][int(state['current_step_id'])]}

            ### 📋 Error History ({len(state['problems'])} attempt(s))

            **Initial Code:**
            {state['initial_code'].model_dump_json() if state.get('initial_code') else '⚠️ No initial code (output format error on first attempt)'}

            **Bug Fix Attempts:**
            {[ f'No{idx} cmd: {each.model_dump_json()}' for idx, each in enumerate(state['problems'])]}

            ### 🔧 Fix Strategy
            - If the fix is quite small, such as fix few lines of code, using `sed` for single-value changes only
            - If the fix is large such as updating many lines of code, or completely rewrite the logic, rewrite the full code.

            ### ✅ Instructions
            1. Analyze the ROOT CAUSE, do not just patch symptoms
            2. Every item in `code_list` MUST have both `file_name` AND `code_text`
            3. Do NOT create versioned files (no script_v2.py, script_fixed.py)
            4. Overwrite the ORIGINAL file
            """
            message = HumanMessage(content=human_prompt)
        else:
            message = HumanMessage(content=system_prompt)
        message_sequence = state["internal_messages"] + [message]
        response_tuple = await safely_ainvoke(model=code_generator_model, message_sequence=message_sequence)
        if not response_tuple[0]:
            return Command(
                goto="code_generator",
                update={
                    **state,
                    "problems": [*state["problems"], Problem(stratch_notepad=str(response_tuple[1]), code_fix=None)]
                }
            )
        response = response_tuple[1]
        if isinstance(response, CodeList) and (response.code_list or response.exe_cmd):
            for each_cmd in response.exe_cmd:
                if 'sed' in each_cmd:
                    print(each_cmd)
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
                goto="code_generator",
                update={
                    **state,
                    "problems": [*state["problems"], Problem(stratch_notepad="Empty response from code generator, please retry", code_fix=None)]
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

async def update_todo_md(*, steps: list[str], current_step_id: int, output: str, thread_id: str)->Todo:
    prompt = prompt = f"""
    The current step has been completed. Summarize what is the output and delievery of the current step.
    Here is the todo.md for this step:
    {steps[current_step_id]}

    Here is the execution output for the completed step:
    {output}

    Return the summerization with execution detail for the following agent to notice
    """
    response = await todo_model.ainvoke(prompt)
    steps[current_step_id] += '\n' + response.updated_step_todo
    
    with open(f"coding_space/{thread_id}/todo.md", "w") as f:
        f.write("\n".join(steps))
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
        await update_todo_md(steps=state["steps"], current_step_id=state["current_step_id"], output=result_tuple[1], thread_id=state["thread_id"])
        return Command(
            goto="code_generator",
            update={
                **state,
                "problems": [],
                "initial_code": None,
                "current_step_id": state["current_step_id"] + 1,
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