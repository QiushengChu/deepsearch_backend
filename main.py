from fastapi import FastAPI
import uvicorn
from model.request_models import ChatRequest
from model.response_models import SessionStatusResponse
import uuid
from routes.ws_routes import ws_router

app = FastAPI()
app.include_router(ws_router)

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