from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .agents.research_agent import ResearchAgent

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

class InitRequest(BaseModel):
    company: str; years: int = 3; dept: str | None = None

class QARequest(BaseModel):
    company: str; question: str

@app.post('/init')
async def init(req: InitRequest):
    agent = ResearchAgent(req.company, req.years, req.dept)
    return {"clarifications": agent.ask_clarifications(), "overview": agent.basic_overview()}

@app.post('/deep')
async def deep(req: InitRequest):
    agent = ResearchAgent(req.company, req.years, req.dept)
    return agent.deep_collect()

@app.post('/qa')
async def qa(req: QARequest):
    agent = ResearchAgent(req.company)
    return agent.answer_with_evidence(req.question)
