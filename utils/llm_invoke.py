# from utils.agent_setup import supervisor_app
import utils.agent_setup as compile_supervisor_app_module ## must import the function as module otherwise the global supervisor_app will be None
from model.session_manager import manager
import asyncio
from langchain_core.messages import HumanMessage

async def invoke(user_input: str, thread_id: str):
    config = {
        "configurable": { "thread_id": thread_id}
    }
    supervisor_app = compile_supervisor_app_module.supervisor_app
    if supervisor_app is None:
        raise Exception("Cannot compile the agent graph")
    ##marking the session in progress
    manager.update_session(thread_id=thread_id, updates={
        "status": "in progress",
        "current_step": "in progress",
        "created_at": asyncio.get_event_loop().time(),
        "message_count": manager.get_session(thread_id=thread_id).get("message_count", 0) + 1
    })
    supervisor_app.aget_state
    await supervisor_app.ainvoke(
        {
            "messages": [HumanMessage(content=user_input)], 
            "sender": "user", 
            "thread_id": thread_id,
            "pause_required": False,
            "message_user": False,
            "input_tokens": 0,
            "output_tokens": 0,
        }, config=config
    )