import utils.agent_setup as complie_supervisor_app_module ## import agent_setup as a module as supervisor_app will be a global variable get initiated post module import
from model.session_manager import manager

async def context_retriveral(thread_id: str):
    supervisor_app = complie_supervisor_app_module.supervisor_app
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }
    if supervisor_app is None:
        raise Exception("supervisor app is none...")
    ## get message states via checkpoint with thread_id
    state = await supervisor_app.aget_state(config)
    ##if the messages is empty then return
    if not state[0].get("messages", []):
        return
    else:
        for message in state[0].get("messages", []):
            if message.type == "human":
                await manager.send_event(thread_id=thread_id, event={
                    "type": "human_input", 
                    "sender": "human",
                    "content": message.content,
                    "fileNames": message.additional_kwargs["file_names"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0
                })
            elif message.type == "ai" and message.additional_kwargs["message_user"]:
                await manager.send_event(thread_id=thread_id, event=message.additional_kwargs["message_event"])
            elif message.type == "tool":
                await manager.send_event(thread_id=thread_id, event=message.additional_kwargs)
    return 
        
                
                
        



    