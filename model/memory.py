from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class CheckpointerManager:
    def __init__(self):
        self.checkpointer = None

    async def initialize(self):
        '''initialize the long-short memory checkpointer'''
        if self.checkpointer is None:
            conn = await aiosqlite.connect(os.getenv("sqlite_db_langgraph_path"))
            self.checkpointer = AsyncSqliteSaver(conn=conn)
        return self.checkpointer
    
    async def close(self):
        '''Closing the checkpointer'''
        if self.checkpointer and self.checkpointer.conn:
            await self.checkpointer.conn.close()

    async def thread_checker(self, session_id: str)->bool:
        conn = self.checkpointer.conn
        try:
            cursor = await conn.execute(f"SELECT thread_id, COUNT(*) FROM checkpoints WHERE thread_id = ? GROUP BY thread_id", (session_id,))
            thread_id_records = await cursor.fetchall()
            return True if thread_id_records else False
        except Exception as e:
            raise f"DB connection error: {e}"
            
    
    async def remove_thread(self, session_id: str)-> dict[str, str]:
        conn = self.checkpointer.conn
        try:
            session_exists = await self.thread_checker(session_id=session_id)
            if session_exists:
                await conn.execute(f"DELETE from checkpoints where thread_id = ?", (session_id,))
                await conn.commit()
                return {"result": True, "message": f"{session_id} has been reomved from long term memory"}
            else:
                return {"result": False, "message": f"{session_id} is invalid"}
        except Exception as e:
            return {"result": "Failed", "message": f"{e}"}
        

checkpointer_manager = CheckpointerManager()

