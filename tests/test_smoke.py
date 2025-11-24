from src.agents.research_agent import ResearchAgent

def test_init():
    agent = ResearchAgent('ACME Corp', 3)
    assert agent.company == 'ACME Corp'
