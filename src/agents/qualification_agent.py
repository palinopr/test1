"""
Customer Qualification Agent using LangGraph StateGraph.

This module implements a conversational AI agent that qualifies customers for automation
services, maintains conversation context, uses GHL tools, and creates personalized responses.
"""

import json
import os
from typing import Dict, Any, List, Optional, TypedDict, Annotated
from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from ..tools.ghl_tools import get_ghl_tools, create_wow_moment_context
from ..config.langsmith_config import get_langsmith_config

logger = structlog.get_logger(__name__)


class QualificationState(TypedDict):
    """State for the customer qualification conversation."""
    messages: Annotated[List, add_messages]
    contact_id: Optional[str]
    contact_info: Optional[Dict[str, Any]]
    qualification_status: str  # "initial", "qualifying", "qualified", "not_qualified", "completed"
    business_info: Dict[str, Any]
    pain_points: List[str]
    automation_interest: Optional[str]
    budget_range: Optional[str]
    timeline: Optional[str]
    next_steps: Optional[str]
    conversation_stage: str  # "greeting", "discovery", "qualification", "presentation", "closing"
    wow_moment_delivered: bool


class CustomerQualificationAgent:
    """
    LangGraph-based customer qualification agent for automation services.
    
    This agent handles the complete customer qualification workflow:
    1. Greeting and rapport building
    2. Discovery of business needs and pain points
    3. Qualification based on budget, timeline, and fit
    4. Presentation of relevant automation solutions
    5. Next steps and follow-up scheduling
    """
    
    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model_name = model_name
        self.llm = None
        self.tools = get_ghl_tools()
        self.tool_node = ToolNode(self.tools)
        self.graph = None
        self.langsmith_config = get_langsmith_config()
        self.memory = MemorySaver()
        
        # Qualification criteria
        self.qualification_criteria = {
            "min_monthly_revenue": 5000,
            "automation_readiness_indicators": [
                "repetitive tasks", "manual processes", "scaling challenges",
                "time consuming", "human error", "efficiency", "growth"
            ],
            "budget_indicators": ["budget", "investment", "cost", "price", "spend"],
            "timeline_indicators": ["when", "timeline", "urgency", "soon", "asap"]
        }
        
        self._initialize_llm()
        self._build_graph()
    
    def _initialize_llm(self):
        """Initialize the language model with tool binding."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        self.llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.7,
            api_key=api_key
        ).bind_tools(self.tools)
        
        logger.info("LLM initialized", model=self.model_name, tools_count=len(self.tools))
    
    def _build_graph(self):
        """Build the LangGraph StateGraph for customer qualification."""
        workflow = StateGraph(QualificationState)
        
        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self.tool_node)
        workflow.add_node("analyze_response", self._analyze_response_node)
        workflow.add_node("update_qualification", self._update_qualification_node)
        workflow.add_node("generate_response", self._generate_response_node)
        
        # Set entry point
        workflow.set_entry_point("agent")
        
        # Add edges
        workflow.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {
                "tools": "tools",
                "continue": "analyze_response"
            }
        )
        
        workflow.add_edge("tools", "analyze_response")
        workflow.add_edge("analyze_response", "update_qualification")
        workflow.add_edge("update_qualification", "generate_response")
        workflow.add_edge("generate_response", END)
        
        # Compile the graph
        self.graph = workflow.compile(
            checkpointer=self.memory,
            interrupt_before=[]  # Can add interrupts for human-in-the-loop if needed
        )
        
        logger.info("LangGraph workflow compiled successfully")
    
    def _agent_node(self, state: QualificationState) -> Dict[str, Any]:
        """Main agent node that processes messages and decides on actions."""
        messages = state["messages"]
        contact_info = state.get("contact_info", {})
        conversation_stage = state.get("conversation_stage", "greeting")
        
        # Create system prompt based on conversation stage and context
        system_prompt = self._create_system_prompt(conversation_stage, contact_info, state)
        
        # Prepare messages for the LLM
        prompt_messages = [SystemMessage(content=system_prompt)] + messages
        
        # Get LLM response
        response = self.llm.invoke(prompt_messages)
        
        return {"messages": [response]}
    
    def _should_use_tools(self, state: QualificationState) -> str:
        """Determine if tools should be used based on the last message."""
        last_message = state["messages"][-1]
        
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        return "continue"
    
    def _analyze_response_node(self, state: QualificationState) -> Dict[str, Any]:
        """Analyze the customer's response to extract qualification information."""
        messages = state["messages"]
        if not messages:
            return {}
        
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        
        if not last_human_message:
            return {}
        
        response_text = last_human_message.content.lower()
        
        # Extract business information
        business_info = state.get("business_info", {})
        pain_points = state.get("pain_points", [])
        
        # Analyze for business size indicators
        if any(indicator in response_text for indicator in ["employees", "team", "staff", "people"]):
            # Extract team size information
            import re
            numbers = re.findall(r'\d+', response_text)
            if numbers:
                business_info["team_size"] = int(numbers[0])
        
        # Analyze for revenue indicators
        if any(indicator in response_text for indicator in ["revenue", "sales", "income", "profit"]):
            business_info["has_revenue_info"] = True
        
        # Extract pain points
        for indicator in self.qualification_criteria["automation_readiness_indicators"]:
            if indicator in response_text:
                if indicator not in pain_points:
                    pain_points.append(indicator)
        
        # Extract budget information
        budget_range = state.get("budget_range")
        if any(indicator in response_text for indicator in self.qualification_criteria["budget_indicators"]):
            # Simple budget extraction logic
            if any(term in response_text for term in ["thousand", "k", "$"]):
                budget_range = "discussed"
        
        # Extract timeline information
        timeline = state.get("timeline")
        if any(indicator in response_text for indicator in self.qualification_criteria["timeline_indicators"]):
            if any(term in response_text for term in ["month", "week", "soon", "asap"]):
                timeline = "short_term"
            elif any(term in response_text for term in ["quarter", "year", "later"]):
                timeline = "long_term"
        
        return {
            "business_info": business_info,
            "pain_points": pain_points,
            "budget_range": budget_range,
            "timeline": timeline
        }
    
    def _update_qualification_node(self, state: QualificationState) -> Dict[str, Any]:
        """Update qualification status based on gathered information."""
        business_info = state.get("business_info", {})
        pain_points = state.get("pain_points", [])
        budget_range = state.get("budget_range")
        timeline = state.get("timeline")
        current_stage = state.get("conversation_stage", "greeting")
        
        # Determine qualification status
        qualification_score = 0
        
        # Score based on pain points (automation readiness)
        if len(pain_points) >= 2:
            qualification_score += 3
        elif len(pain_points) >= 1:
            qualification_score += 1
        
        # Score based on business size
        if business_info.get("team_size", 0) > 5:
            qualification_score += 2
        elif business_info.get("team_size", 0) > 1:
            qualification_score += 1
        
        # Score based on budget discussion
        if budget_range:
            qualification_score += 2
        
        # Score based on timeline
        if timeline == "short_term":
            qualification_score += 2
        elif timeline == "long_term":
            qualification_score += 1
        
        # Determine qualification status
        if qualification_score >= 6:
            qualification_status = "qualified"
        elif qualification_score >= 3:
            qualification_status = "qualifying"
        else:
            qualification_status = "initial"
        
        # Update conversation stage based on information gathered
        new_stage = current_stage
        if current_stage == "greeting" and len(pain_points) > 0:
            new_stage = "discovery"
        elif current_stage == "discovery" and qualification_score >= 3:
            new_stage = "qualification"
        elif current_stage == "qualification" and qualification_score >= 6:
            new_stage = "presentation"
        
        return {
            "qualification_status": qualification_status,
            "conversation_stage": new_stage
        }
    
    def _generate_response_node(self, state: QualificationState) -> Dict[str, Any]:
        """Generate the final response based on current state."""
        # This node can be used for additional response processing
        # For now, we'll just pass through since the main response is generated in the agent node
        return {}
    
    def _create_system_prompt(self, stage: str, contact_info: Dict[str, Any], state: QualificationState) -> str:
        """Create a dynamic system prompt based on conversation stage and context."""
        
        # Base personality and role
        base_prompt = """You are an expert automation consultant specializing in helping businesses streamline their operations through intelligent automation solutions. You are friendly, professional, and genuinely interested in helping businesses grow.

Your goal is to qualify potential customers for automation services by understanding their business needs, pain points, and readiness for automation solutions.

IMPORTANT GUIDELINES:
1. Always be conversational and natural - avoid sounding robotic or scripted
2. Ask ONE question at a time to avoid overwhelming the customer
3. Listen actively and reference what they've shared previously
4. Create "wow moments" by demonstrating knowledge about their business or industry
5. Use the available tools to send messages, add tags, and create notes
6. Be helpful even if they don't qualify - provide value in every interaction

"""
        
        # Add stage-specific instructions
        stage_prompts = {
            "greeting": """
CURRENT STAGE: GREETING & RAPPORT BUILDING
- Start with a warm, personalized greeting
- Reference how they found you (if known from contact info)
- Ask about their business in a natural, curious way
- Begin to understand their industry and current challenges
- Keep it conversational and build rapport
""",
            
            "discovery": """
CURRENT STAGE: DISCOVERY
- You've established initial rapport, now dig deeper into their business
- Ask about their current processes and workflows
- Identify pain points and inefficiencies
- Understand their team size and structure
- Listen for automation opportunities
- Show genuine interest in their challenges
""",
            
            "qualification": """
CURRENT STAGE: QUALIFICATION
- You understand their pain points, now assess fit and readiness
- Explore their budget considerations (tactfully)
- Understand their timeline and urgency
- Assess their openness to change and automation
- Determine if they're a good fit for your services
""",
            
            "presentation": """
CURRENT STAGE: PRESENTATION
- They're qualified! Now present relevant solutions
- Share specific automation ideas for their pain points
- Provide examples of similar businesses you've helped
- Create excitement about the possibilities
- Begin discussing next steps
""",
            
            "closing": """
CURRENT STAGE: CLOSING
- Summarize the value proposition
- Address any final concerns
- Propose clear next steps
- Schedule follow-up or consultation
- Ensure they feel confident about moving forward
"""
        }
        
        prompt = base_prompt + stage_prompts.get(stage, stage_prompts["greeting"])
        
        # Add contact context if available
        if contact_info:
            wow_context = create_wow_moment_context(contact_info)
            if wow_context != "No additional context available":
                prompt += f"\n\nCONTACT CONTEXT (use this to personalize your response):\n{wow_context}\n"
        
        # Add current qualification state
        qualification_status = state.get("qualification_status", "initial")
        pain_points = state.get("pain_points", [])
        business_info = state.get("business_info", {})
        
        if pain_points:
            prompt += f"\nIDENTIFIED PAIN POINTS: {', '.join(pain_points)}\n"
        
        if business_info:
            prompt += f"\nBUSINESS INFO GATHERED: {json.dumps(business_info, indent=2)}\n"
        
        prompt += f"\nCURRENT QUALIFICATION STATUS: {qualification_status}\n"
        
        # Add tool usage instructions
        prompt += """
AVAILABLE TOOLS:
- send_message: Send SMS/Email/WhatsApp to the contact
- add_contact_tag: Tag contacts (use tags like 'qualified', 'interested', 'automation-prospect')
- create_contact_note: Record important conversation details
- update_contact: Update contact information
- get_contact_details: Get more context about the contact

Use these tools strategically to enhance the conversation and track progress.
"""
        
        return prompt
    
    async def process_message(
        self, 
        message: str, 
        contact_id: str, 
        contact_info: Optional[Dict[str, Any]] = None,
        thread_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a customer message and generate a response.
        
        Args:
            message: The customer's message
            contact_id: GHL contact ID
            contact_info: Optional contact information for context
            thread_id: Optional thread ID for conversation continuity
            
        Returns:
            Dict containing the response and updated state
        """
        try:
            # Create or get thread ID
            if not thread_id:
                thread_id = f"contact_{contact_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Prepare initial state
            config = {"configurable": {"thread_id": thread_id}}
            
            # Get current state or initialize
            try:
                current_state = self.graph.get_state(config)
                if current_state.values:
                    state = current_state.values
                else:
                    state = self._initialize_state(contact_id, contact_info)
            except:
                state = self._initialize_state(contact_id, contact_info)
            
            # Add the new human message
            human_message = HumanMessage(content=message)
            
            # Process through the graph
            result = await self.graph.ainvoke(
                {"messages": [human_message]},
                config=config
            )
            
            # Extract the AI response
            ai_response = None
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    ai_response = msg.content
                    break
            
            logger.info(
                "Message processed successfully",
                contact_id=contact_id,
                thread_id=thread_id,
                qualification_status=result.get("qualification_status", "unknown")
            )
            
            return {
                "response": ai_response or "I'm here to help! Could you tell me more about your business?",
                "qualification_status": result.get("qualification_status", "initial"),
                "conversation_stage": result.get("conversation_stage", "greeting"),
                "thread_id": thread_id,
                "state": result
            }
            
        except Exception as e:
            logger.error("Error processing message", error=str(e), contact_id=contact_id)
            return {
                "response": "I apologize, but I'm having a technical issue. Let me help you - could you tell me about your business and what challenges you're facing?",
                "qualification_status": "initial",
                "conversation_stage": "greeting",
                "thread_id": thread_id,
                "error": str(e)
            }
    
    def _initialize_state(self, contact_id: str, contact_info: Optional[Dict[str, Any]]) -> QualificationState:
        """Initialize the conversation state."""
        return QualificationState(
            messages=[],
            contact_id=contact_id,
            contact_info=contact_info or {},
            qualification_status="initial",
            business_info={},
            pain_points=[],
            automation_interest=None,
            budget_range=None,
            timeline=None,
            next_steps=None,
            conversation_stage="greeting",
            wow_moment_delivered=False
        )
    
    def get_qualification_summary(self, thread_id: str) -> Dict[str, Any]:
        """Get a summary of the qualification status for a conversation thread."""
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = self.graph.get_state(config)
            
            if not state.values:
                return {"error": "No conversation found for this thread"}
            
            return {
                "contact_id": state.values.get("contact_id"),
                "qualification_status": state.values.get("qualification_status", "initial"),
                "conversation_stage": state.values.get("conversation_stage", "greeting"),
                "business_info": state.values.get("business_info", {}),
                "pain_points": state.values.get("pain_points", []),
                "budget_range": state.values.get("budget_range"),
                "timeline": state.values.get("timeline"),
                "next_steps": state.values.get("next_steps"),
                "message_count": len(state.values.get("messages", []))
            }
            
        except Exception as e:
            logger.error("Error getting qualification summary", error=str(e), thread_id=thread_id)
            return {"error": str(e)}


# Global agent instance
_agent_instance = None


def get_qualification_agent() -> CustomerQualificationAgent:
    """Get the global qualification agent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerQualificationAgent()
    return _agent_instance


async def qualify_customer(
    message: str,
    contact_id: str,
    contact_info: Optional[Dict[str, Any]] = None,
    thread_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to qualify a customer with a single message.
    
    Args:
        message: Customer's message
        contact_id: GHL contact ID
        contact_info: Optional contact information
        thread_id: Optional conversation thread ID
        
    Returns:
        Dict with response and qualification information
    """
    agent = get_qualification_agent()
    return await agent.process_message(message, contact_id, contact_info, thread_id)
