from typing import Dict
from fastapi import WebSocket
import asyncio

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.session_states: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, thread_id: str):
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        self.session_states[thread_id] = {
            "status": "idle",
            "current_step": None,
            "created_at": asyncio.get_event_loop().time(),
            "message_count": 0
        }
        print(f"client ws connect: {thread_id}")
        
    
    async def disconnect(self, thread_id: str):
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        if thread_id in self.session_states:
            del self.session_states[thread_id]
        print(f"Client disconnected")

    async def send_event(self, thread_id: str, event: dict):
        if thread_id in self.active_connections:
            try:
                event_with_meta = {
                    "event_id": f"evt_{str(self.session_states[thread_id]['message_count'])}",
                    "timestamp": asyncio.get_event_loop().time(),
                    **event
                }
                await self.active_connections[thread_id].send_json(event_with_meta)
                self.session_states[thread_id]['message_count'] += 1             
            except Exception as e:
                print(f"Send event failed {thread_id}: {e}")
    
    def get_session(self, thread_id: str):
        return self.session_states.get(thread_id)
    
    def update_session(self, thread_id: str, updates: dict):
        if thread_id in self.session_states:
            self.session_states[thread_id].update(updates)

manager = ConnectionManager()