from langgraph.graph import END, StateGraph

from backend.agent.orchestrator import orchestrator_node, router_edge
from backend.agent.state import AgentState
from backend.agent.sub_agents import research_node, risk_node, sentiment_node
from backend.agent.synthesis import after_validation, synthesis_node, validator_node


def build_graph():
    """
    orchestrator -> (research | sentiment | risk, in parallel) -> synthesis -> validator
                                                                   ^              |
                                                                   +-- revise ----+  (max one revision)
    """
    g = StateGraph(AgentState)
    g.add_node("orchestrator_node", orchestrator_node)
    g.add_node("research_node", research_node)
    g.add_node("sentiment_node", sentiment_node)
    g.add_node("risk_node", risk_node)
    g.add_node("synthesis_node", synthesis_node)
    g.add_node("validator_node", validator_node)

    g.set_entry_point("orchestrator_node")
    g.add_conditional_edges("orchestrator_node", router_edge,
                            ["research_node", "sentiment_node", "risk_node", "synthesis_node"])
    for n in ("research_node", "sentiment_node", "risk_node"):
        g.add_edge(n, "synthesis_node")
    g.add_edge("synthesis_node", "validator_node")
    g.add_conditional_edges("validator_node", after_validation, {"synthesis_node": "synthesis_node", "__end__": END})
    return g.compile()


app = build_graph()
