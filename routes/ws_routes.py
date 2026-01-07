from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from model.session_manager import manager
import json
import asyncio
from utils.context_retriver import context_retriveral
from model.prompt_cache_model import prompt_cache
from utils.llm_invoke import invoke
from model.memory import checkpointer_manager
from dotenv import load_dotenv

load_dotenv()
ws_router = APIRouter()


async def run_workflow_with_generator(thread_id: str, user_message: str):
    """运行带 yield 的工作流"""
    
    print(f"🚀 开始工作流: {thread_id} - {user_message}")
    
    try:
        # 🎯 关键：遍历 async generator 的每个 yield
        # async for event in agent_async_generator(thread_id, user_message):
        #     # 实时发送每个事件到前端
        #     await manager.send_event(thread_id, event)
        #     print(f"📨 发送事件: {event['type']}")
        await invoke(user_input=user_message, thread_id=thread_id)
             
    except Exception as e:
        # 🎯 错误处理
        error_event = {
            "type": "workflow_error",
            "message": f"工作流执行失败: {str(e)}",
            "error": str(e)
        }
        await manager.send_event(thread_id, error_event)
        print(f"❌ 工作流错误: {e}")
        
        manager.update_session(thread_id, {
            "status": "idle",
            "current_step": "NA"
        })

@ws_router.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await manager.connect(websocket=websocket, thread_id=thread_id)
    await context_retriveral(thread_id=thread_id)
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            print(f"received prompt: {message_data}")
            
            if message_data["type"] == "start_workflow":
                user_message = message_data["message"]
                asyncio.create_task(run_workflow_with_generator(thread_id=thread_id, user_message=user_message))
            elif message_data["type"] == "user_clarify_response": ##handle hard pause response
                message_content = message_data.get("message", None)
                if message_content == None:
                    await manager.send_event(thread_id=thread_id, event={
                        "type": "message_error",
                        "sender": "message_validator",
                        "content": "Please provide a valid content"
                    })
                else:
                    asyncio.create_task(run_workflow_with_generator(thread_id=thread_id, user_message=message_content))
            elif message_data["type"] == "user_prompt" and manager.get_session(thread_id=thread_id)["status"] == "in progress":
                prompt_cache.session[thread_id].append({"type": "user_prompt", "message": message_data.get("message")})
            elif message_data["type"] == "user_prompt" and manager.get_session(thread_id=thread_id)["status"] == "idle":
                asyncio.create_task(run_workflow_with_generator(thread_id=thread_id, user_message=message_data.get("message", None)))

            elif message_data["type"] == "ping":
                await manager.send_event(thread_id=thread_id, event={"type": "pong"})
    except WebSocketDisconnect:
        print(f"[{thread_id}] WebSocket disconnected")
    except Exception as e:
        print(f"[{thread_id}] Websocket error: {e}")
    finally:
        await manager.disconnect(thread_id=thread_id)
        # await memory.
   

# @ws_router.delete("/api/{session_id}")
# async def delete_session(session_id: str)->JSONResponse:
#     result = await checkpointer_manager.remove_thread(session_id=session_id)
#     if result["result"] == True:
#         return JSONResponse(status_code=status.HTTP_200_OK, content={
#             "status": f"{session_id} has been removed from long-term memory"
#         })
#     elif result["result"] == False:
#         return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={
#             "error": f"{session_id} is not valid"
#         })
#     else:
#         return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={
#             "error": result["message"]
#         })

