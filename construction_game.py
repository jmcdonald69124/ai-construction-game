import os
import sqlite3
import random
import sys
from typing import TypedDict, List, Annotated
import operator
from langchain_community.chat_models import ChatOllama
from langgraph.graph import StateGraph, START, END
from opentelemetry.sdk.resources import Resource
from opentelemetry import trace

# --- 0. OBSERVABILITY SETUP ---
from phoenix.otel import register
from openinference.instrumentation.langchain import LangChainInstrumentor
# Only run tracing if we are in the docker container
if os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
    print("🔭 Connecting to Phoenix Observability...")
    resource = Resource(attributes={"service.name": "construction-crew"})
    tracer_provider = register(
        project_name="GeneralContractorHQ",
        endpoint=os.getenv("PHOENIX_COLLECTOR_ENDPOINT"),
        resource=resource
    )
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
# --- 1. THE JOB SITE (Database) ---
DB_NAME = "game_site.db" # Local file
def init_game():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS house')
    c.execute('CREATE TABLE house (component TEXT PRIMARY KEY, status TEXT)')
    c.execute('DROP TABLE IF EXISTS budget')
    c.execute('CREATE TABLE budget (amount INTEGER)')
    c.execute('INSERT INTO budget VALUES (2000)') 
    conn.commit()
    conn.close()
def get_budget():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT amount FROM budget')
    amt = c.fetchone()[0]
    conn.close()
    return amt
def fine_player(amount, reason):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE budget SET amount = amount - ?', (amount,))
    conn.commit()
    conn.close()
    return f"🚨 FINE ISSUED: ${amount} for {reason}"
def pay_worker(amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE budget SET amount = amount - ?', (amount,))
    conn.commit()
    conn.close()
def build_component(component):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT component FROM house')
    existing = [row[0] for row in c.fetchall()]
    
    # Process Guardrail: Physical dependencies
    if component == "FRAMING" and "FOUNDATION" not in existing:
        return False, "MISSING_DEPENDENCY: Foundation"
    if component == "ROOF" and "FRAMING" not in existing:
        return False, "MISSING_DEPENDENCY: Framing"
        
    c.execute('INSERT OR REPLACE INTO house VALUES (?, ?)', (component, 'BUILT'))
    conn.commit()
    conn.close()
    return True, "SUCCESS"
def get_site_state():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT component FROM house')
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]
# --- 2. THE AI MODEL ---
# Using Llama3 via Ollama
ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
llm = ChatOllama(model="llama3", temperature=0, base_url=ollama_host)
# --- 3. THE GRAPH STATE ---
class GameState(TypedDict):
    messages: Annotated[List[str], operator.add]
    next_step: str
    worker_claim: str
    safety_violation: bool
# --- 4. THE LAYERS ---
# [LAYER 1] THE GUARDRAIL (Site Safety Officer)
def safety_guardrail_node(state):
    trace.get_current_span().set_attribute("agent.type", "safety_guardrail")
    user_input = state['messages'][-1].lower()
    forbidden_words = [
        "asbestos", "lead paint", "bribe", "fire", "explode", "kill",
        "dynamite", "insurance fraud", "cut corners", "cheap materials",
        "unlicensed", "illegal", "dump"
    ]
    
    for word in forbidden_words:
        if word in user_input:
            print(f"\n🚫 GUARDRAIL TRIGGERED: Detected unsafe term '{word}'")
            return {
                "messages": [f"SAFETY OFFICER: Access Denied. The term '{word}' violates job site safety protocols. This incident has been logged."],
                "safety_violation": True,
                "next_step": "BLOCKED"
            }
    print(f"🛡️  SAFETY OFFICER: Input '{user_input}' cleared safety checks.")
    return {"safety_violation": False}
# [LAYER 2] THE SUPERVISOR (Router)
def supervisor_node(state):
    trace.get_current_span().set_attribute("agent.type", "supervisor")
    user_input = state['messages'][-1]
    prompt = f"""
    You are a Construction Site Supervisor managing a house build.
    User Command: "{user_input}"
    
    Map this to a worker team:
    - FOUNDATION (concrete, slab, base)
    - FRAMING (walls, wood, frame)
    - ELECTRICAL (lights, wiring, power)
    - ROOF (shingles, top, cover)
    - CHAT (anything else, including pools, plumbing, painting, landscaping, or questions)
    
    If the request is for something we don't do (like pools), choose CHAT.
    
    Respond ONLY with the category word.
    """
    print(f"👷 SUPERVISOR: Analyzing request via LLM...")
    response = llm.invoke(prompt)
    decision = response.content.strip().upper()
    
    valid = ["FOUNDATION", "FRAMING", "ELECTRICAL", "ROOF", "CHAT"]
    if decision not in valid: decision = "CHAT"
    
    print(f"👷 SUPERVISOR: Decision -> Assign to {decision} Team.")
    return {"next_step": decision}
# [LAYER 3] THE WORKERS
def worker_node(state):
    task_type = state["next_step"]
    
    span = trace.get_current_span()
    span.set_attribute("agent.type", "worker")
    span.set_attribute("worker.team", task_type)
    
    pay_worker(200) 
    print(f"🔨 {task_type} TEAM: Received orders. Getting to work...")
    
    is_lazy = random.random() < 0.3 # 30% chance of hallucination
    
    if is_lazy:
        claim = f"The {task_type} team reports: Job done, looks great!"
        # Engaging Hallucination Prompt
        print(f"\n[🚧 SYSTEM ALEART] The {task_type} Foreman is looking suspicious...")
        print(f"   (He's drinking a smoothie and his crew is sleeping)")
    else:
        success, msg = build_component(task_type)
        if success:
            claim = f"The {task_type} team reports: Job done, looks great!"
        else:
            claim = f"The {task_type} team reports: We couldn't start. {msg}"
    return {"messages": [claim], "worker_claim": claim}
# [LAYER 4] THE INSPECTOR
def inspector_node(state):
    trace.get_current_span().set_attribute("agent.type", "inspector")
    claim = state.get("worker_claim", "")
    task_type = state["next_step"]
    actual_site = get_site_state()
    
    print(f"🔍 INSPECTOR: Reviewing work... (Site State: {actual_site})")

    if "Job done" in claim:
        if task_type in actual_site:
            msg = "Inspector: ✅ Verified. Work matches blueprints."
        else:
            msg = fine_player(500, "FRAUD! Worker claimed completion but nothing was built.")
    elif "MISSING_DEPENDENCY" in claim:
         msg = fine_player(200, "CODE VIOLATION! You tried to build out of order.")
    else:
        msg = "Inspector: No work claimed."
    return {"messages": [msg]}
# [LAYER 5] THE JUDGE (Post-incident Review)
def judge_node(state):
    trace.get_current_span().set_attribute("agent.type", "judge")
    
    user_input = state['messages'][0]
    worker_claim = state.get("worker_claim", "No claim.")
    inspector_ruling = state['messages'][-1]
    
    # Only judge if there was work done or a fine issued
    if "Inspector" not in inspector_ruling and "FINE" not in inspector_ruling:
        return {}

    prompt = f"""
    You are the City Permit Office Review Board.
    Review this incident:
    1. Client Order: "{user_input}"
    2. Worker Claim: "{worker_claim}"
    3. Inspector Ruling: "{inspector_ruling}"

    Provide a short, authoritative, and witty permit ruling.
    - If the worker failed or hallucinated (claimed work but inspector flagged fraud), REVOKE their license.
    - If the order was invalid (bad dependency), cite the client for code violation.
    - If successful, STAMP the permit APPROVED.
    
    Start with "📝 PERMIT OFFICE:"
    """
    
    print(f"📝 PERMIT OFFICE: Reviewing case...")
    response = llm.invoke(prompt)
    ruling = response.content.strip()
    
    return {"messages": [ruling]}
def chatbot_node(state):
    user_input = state['messages'][0]
    current_site = get_site_state()
    
    if "FOUNDATION" not in current_site:
        next_task = "pouring the FOUNDATION"
    elif "FRAMING" not in current_site:
        next_task = "building the FRAMING"
    elif "ELECTRICAL" not in current_site:
        next_task = "installing ELECTRICAL"
    elif "ROOF" not in current_site:
        next_task = "finishing the ROOF"
    else:
        next_task = "celebrating (House Complete)"

    prompt = f"""
    You are a grumpy Construction Site Supervisor.
    The client asked: "{user_input}"
    
    We ONLY do: Foundation, Framing, Electrical, and Roof.
    We do NOT do: Pools, landscaping, plumbing, painting, or idle chat.
    
    Reject the client's request. Tell them to focus.
    Remind them that we should be working on: {next_task}.
    
    Keep it short (1 sentence).
    """
    
    print(f"👷 SUPERVISOR: Grumbling at client...")
    response = llm.invoke(prompt)
    return {"messages": [f"Supervisor: {response.content.strip()}"]}
# --- 5. BUILD THE GRAPH ---
workflow = StateGraph(GameState)
workflow.add_node("guardrail", safety_guardrail_node)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("worker", worker_node)
workflow.add_node("inspector", inspector_node)
workflow.add_node("judge", judge_node)
workflow.add_node("chatbot", chatbot_node)
workflow.set_entry_point("guardrail")
def route_guardrail(state):
    if state.get("safety_violation"): return END
    return "supervisor"
workflow.add_conditional_edges("guardrail", route_guardrail, {"supervisor": "supervisor", END: END})
def route_supervisor(state):
    if state["next_step"] == "CHAT": return "chatbot"
    return "worker"
workflow.add_conditional_edges("supervisor", route_supervisor, {"chatbot": "chatbot", "worker": "worker"})
workflow.add_edge("worker", "inspector")
workflow.add_edge("inspector", "judge")
workflow.add_edge("judge", END)
workflow.add_edge("chatbot", END)
app = workflow.compile()
# --- 6. GAME LOOP ---
def play_game():
    init_game()
    print("\n---------------------------------------------------------")
    print("🏗️  AI CONSTRUCTION SIMULATOR: AGENTIC WORKFLOW DEMO 🏗️")
    print("---------------------------------------------------------")
    print("OBJECTIVE: Build a complete house within the $2000 budget.")
    print("REQUIRED STEPS (In Order):")
    print("  1. FOUNDATION [- $200]")
    print("  2. FRAMING    [- $200]")
    print("  3. ELECTRICAL [- $200]")
    print("  4. ROOF       [- $200]")
    print("\nRULES:")
    print("  - Strict safety protocols active (No shortcuts, no hazards).")
    print("  - The Inspector verifies all work.")
    print("  - Agents may hallucinate (30% chance). Watch your budget!")
    print("---------------------------------------------------------")
    
    while True:
        budget = get_budget()
        site = get_site_state()
        print(f"\n💰 Current Budget: ${budget} | 🏠 Site Progress: {site}")
        
        if budget <= 0:
            print("💀 BANKRUPT.")
            break
        if len(site) == 4:
            print("🎉 HOUSE COMPLETED!")
            break
        
        try:
            # More engaging prompt
            if not site:
                 prompt_text = "CLIENT ORDER (Start with the Foundation) >> "
            elif len(site) == 3:
                 prompt_text = "CLIENT ORDER (Final Step!) >> "
            else:
                 prompt_text = "CLIENT ORDER >> "
                 
            user_input = input(prompt_text)
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Exiting game...")
            break

        if user_input.lower() in ["quit", "exit"]: break
        
        inputs = {"messages": [user_input]}
        result = app.invoke(inputs)
        
        for m in result['messages'][1:]:
            print(f"  {m}")
if __name__ == "__main__":
    play_game()