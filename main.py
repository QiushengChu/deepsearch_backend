from fastapi import FastAPI
import uvicorn
import uuid
from routes.ws_routes import ws_router
from routes.session_routes import session_router
from utils.agent_setup import agent_compile
from fastapi.middleware.cors import CORSMiddleware
from model.sqlite import create_tables


app = FastAPI()
app.include_router(ws_router)
app.include_router(session_router)

origins = ["*"]

app.add_middleware(CORSMiddleware, allow_origins=origins)


@app.on_event("startup")
async def startup():
    await create_tables()
    await agent_compile()
    # chromadb_client = Chromadb_agent()


@app.get("/")
def read_root():
    return {"message": "Hello World"}


@app.post("/create_session")
def create_thread_id():
    '''Create new session'''
    thread_id = f"session_{uuid.uuid4().hex[:8]}"
    return {
        "thread_id": thread_id
    }


def main():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

if __name__ == "__main__":
    main()