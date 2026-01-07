from model.memory import checkpointer_manager
# from model.async_deep_search_agent import supervisor_app_graph
from model.agents import supervisor

supervisor_app = None


async def agent_compile():
    global supervisor_app
    await checkpointer_manager.initialize()
    print(f"checkpoint memory is initialized")
    # supervisor_app = supervisor_app_graph.compile(checkpointer=checkpointer_manager.checkpointer)
    supervisor_app = supervisor.supervisor_app_graph.compile(checkpointer=checkpointer_manager.checkpointer)
    print("supervisor_app compile succeed...")