from fastapi import FastAPI
from pydantic import BaseModel
from agent import chat

app = FastAPI()


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
def chat_endpoint(body: ChatIn):      # plain def -> FastAPI runs it in a thread pool
    return {"reply": chat(body.session_id, body.message)}
