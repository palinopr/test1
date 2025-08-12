"""
Conversation State Management for Customer Qualification System.

This module provides comprehensive state management for customer qualification conversations,
including persistent state across webhook calls, memory optimization, and context management.
"""

import os
import json
import sqlite3
from typing import Dict, Any, List, Optional, TypedDict, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

import structlog
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.base import BaseCheckpointSaver

logger = structlog.get_logger(__name__)


class QualificationStatus(Enum):
    """Enumeration of qualification statuses."""
    INITIAL = "initial"
    QUALIFYING = "qualifying"
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    COMPLETED = "completed"


class ConversationStage(Enum):
    """Enumeration of conversation stages."""
    GREETING = "greeting"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    PRESENTATION = "presentation"
    CLOSING = "closing"
    COMPLETED = "completed"


@dataclass
class CustomerInfo:
    """Customer information data structure."""
    contact_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    source: Optional[str] = None
    custom_fields: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.custom_fields is None:
            self.custom_fields = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CustomerInfo':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class BusinessInfo:
    """Business information data structure."""
    industry: Optional[str] = None
    team_size: Optional[int] = None
    monthly_revenue: Optional[str] = None
    business_type: Optional[str] = None
    current_tools: List[str] = None
    pain_points: List[str] = None
    automation_experience: Optional[str] = None
    
    def __post_init__(self):
        if self.current_tools is None:
            self.current_tools = []
        if self.pain_points is None:
            self.pain_points = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BusinessInfo':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class QualificationData:
    """Qualification assessment data structure."""
    status: QualificationStatus = QualificationStatus.INITIAL
    score: int = 0
    budget_range: Optional[str] = None
    timeline: Optional[str] = None
    decision_maker: Optional[bool] = None
    automation_readiness: Optional[int] = None  # 1-10 scale
    fit_score: Optional[int] = None  # 1-10 scale
    notes: List[str] = None
    
    def __post_init__(self):
        if self.notes is None:
            self.notes = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QualificationData':
        """Create from dictionary."""
        if 'status' in data:
            data['status'] = QualificationStatus(data['status'])
        return cls(**data)


@dataclass
class ConversationMetrics:
    """Conversation metrics and analytics."""
    message_count: int = 0
    response_time_avg: float = 0.0
    engagement_score: float = 0.0
    sentiment_score: float = 0.0
    topics_discussed: List[str] = None
    questions_asked: int = 0
    tools_used: List[str] = None
    
    def __post_init__(self):
        if self.topics_discussed is None:
            self.topics_discussed = []
        if self.tools_used is None:
            self.tools_used = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationMetrics':
        """Create from dictionary."""
        return cls(**data)


class ConversationState:
    """
    Comprehensive conversation state management.
    
    Manages all aspects of a customer qualification conversation including:
    - Customer and business information
    - Qualification status and scoring
    - Conversation stage and flow
    - Message history and context
    - Performance metrics and analytics
    """
    
    def __init__(
        self,
        thread_id: str,
        customer_info: CustomerInfo,
        business_info: Optional[BusinessInfo] = None,
        qualification_data: Optional[QualificationData] = None
    ):
        self.thread_id = thread_id
        self.customer_info = customer_info
        self.business_info = business_info or BusinessInfo()
        self.qualification_data = qualification_data or QualificationData()
        
        # Conversation flow
        self.conversation_stage = ConversationStage.GREETING
        self.last_activity = datetime.utcnow()
        self.created_at = datetime.utcnow()
        
        # Context and memory
        self.context_summary = ""
        self.key_insights = []
        self.next_actions = []
        
        # Metrics
        self.metrics = ConversationMetrics()
        
        # Flags
        self.wow_moment_delivered = False
        self.follow_up_scheduled = False
        self.needs_human_handoff = False
    
    def update_customer_info(self, updates: Dict[str, Any]) -> None:
        """Update customer information."""
        for key, value in updates.items():
            if hasattr(self.customer_info, key):
                setattr(self.customer_info, key, value)
            elif key == 'custom_fields' and isinstance(value, dict):
                self.customer_info.custom_fields.update(value)
        
        self.last_activity = datetime.utcnow()
        logger.info("Customer info updated", thread_id=self.thread_id, updates=list(updates.keys()))
    
    def update_business_info(self, updates: Dict[str, Any]) -> None:
        """Update business information."""
        for key, value in updates.items():
            if hasattr(self.business_info, key):
                if key in ['current_tools', 'pain_points'] and isinstance(value, list):
                    # Merge lists without duplicates
                    current_list = getattr(self.business_info, key)
                    for item in value:
                        if item not in current_list:
                            current_list.append(item)
                else:
                    setattr(self.business_info, key, value)
        
        self.last_activity = datetime.utcnow()
        logger.info("Business info updated", thread_id=self.thread_id, updates=list(updates.keys()))
    
    def update_qualification(self, updates: Dict[str, Any]) -> None:
        """Update qualification data and recalculate score."""
        for key, value in updates.items():
            if hasattr(self.qualification_data, key):
                if key == 'notes' and isinstance(value, list):
                    # Merge notes
                    for note in value:
                        if note not in self.qualification_data.notes:
                            self.qualification_data.notes.append(note)
                else:
                    setattr(self.qualification_data, key, value)
        
        # Recalculate qualification score
        self._calculate_qualification_score()
        
        self.last_activity = datetime.utcnow()
        logger.info(
            "Qualification updated",
            thread_id=self.thread_id,
            status=self.qualification_data.status.value,
            score=self.qualification_data.score
        )
    
    def _calculate_qualification_score(self) -> None:
        """Calculate qualification score based on available data."""
        score = 0
        
        # Business size indicators
        if self.business_info.team_size:
            if self.business_info.team_size > 10:
                score += 3
            elif self.business_info.team_size > 5:
                score += 2
            elif self.business_info.team_size > 1:
                score += 1
        
        # Revenue indicators
        if self.business_info.monthly_revenue:
            revenue_str = self.business_info.monthly_revenue.lower()
            if any(indicator in revenue_str for indicator in ['100k', '50k', 'six figure']):
                score += 4
            elif any(indicator in revenue_str for indicator in ['20k', '15k', '10k']):
                score += 3
            elif any(indicator in revenue_str for indicator in ['5k', '3k']):
                score += 2
        
        # Pain points (automation readiness)
        pain_point_score = min(len(self.business_info.pain_points), 5)
        score += pain_point_score
        
        # Budget discussion
        if self.qualification_data.budget_range:
            score += 2
        
        # Timeline urgency
        if self.qualification_data.timeline:
            if 'asap' in self.qualification_data.timeline.lower() or 'urgent' in self.qualification_data.timeline.lower():
                score += 3
            elif 'month' in self.qualification_data.timeline.lower():
                score += 2
            elif 'quarter' in self.qualification_data.timeline.lower():
                score += 1
        
        # Decision maker status
        if self.qualification_data.decision_maker is True:
            score += 2
        elif self.qualification_data.decision_maker is False:
            score -= 1
        
        # Update score and status
        self.qualification_data.score = score
        
        # Update status based on score
        if score >= 10:
            self.qualification_data.status = QualificationStatus.QUALIFIED
        elif score >= 6:
            self.qualification_data.status = QualificationStatus.QUALIFYING
        elif score <= 2:
            self.qualification_data.status = QualificationStatus.NOT_QUALIFIED
        else:
            self.qualification_data.status = QualificationStatus.INITIAL
    
    def advance_conversation_stage(self) -> ConversationStage:
        """Advance to the next conversation stage based on current state."""
        current_stage = self.conversation_stage
        
        # Stage progression logic
        if current_stage == ConversationStage.GREETING:
            if len(self.business_info.pain_points) > 0:
                self.conversation_stage = ConversationStage.DISCOVERY
        
        elif current_stage == ConversationStage.DISCOVERY:
            if self.qualification_data.score >= 3:
                self.conversation_stage = ConversationStage.QUALIFICATION
        
        elif current_stage == ConversationStage.QUALIFICATION:
            if self.qualification_data.status == QualificationStatus.QUALIFIED:
                self.conversation_stage = ConversationStage.PRESENTATION
            elif self.qualification_data.status == QualificationStatus.NOT_QUALIFIED:
                self.conversation_stage = ConversationStage.COMPLETED
        
        elif current_stage == ConversationStage.PRESENTATION:
            if self.follow_up_scheduled or self.needs_human_handoff:
                self.conversation_stage = ConversationStage.CLOSING
        
        elif current_stage == ConversationStage.CLOSING:
            self.conversation_stage = ConversationStage.COMPLETED
        
        if self.conversation_stage != current_stage:
            logger.info(
                "Conversation stage advanced",
                thread_id=self.thread_id,
                from_stage=current_stage.value,
                to_stage=self.conversation_stage.value
            )
        
        return self.conversation_stage
    
    def update_metrics(self, message_count_delta: int = 0, tools_used: List[str] = None) -> None:
        """Update conversation metrics."""
        self.metrics.message_count += message_count_delta
        
        if tools_used:
            for tool in tools_used:
                if tool not in self.metrics.tools_used:
                    self.metrics.tools_used.append(tool)
        
        # Calculate engagement score based on message count and stage progression
        stage_weight = {
            ConversationStage.GREETING: 1,
            ConversationStage.DISCOVERY: 2,
            ConversationStage.QUALIFICATION: 3,
            ConversationStage.PRESENTATION: 4,
            ConversationStage.CLOSING: 5,
            ConversationStage.COMPLETED: 5
        }
        
        base_engagement = min(self.metrics.message_count * 0.1, 5.0)
        stage_bonus = stage_weight.get(self.conversation_stage, 1) * 0.5
        qualification_bonus = self.qualification_data.score * 0.1
        
        self.metrics.engagement_score = min(base_engagement + stage_bonus + qualification_bonus, 10.0)
    
    def get_context_summary(self, max_length: int = 500) -> str:
        """Get a concise context summary for the conversation."""
        summary_parts = []
        
        # Customer info
        if self.customer_info.first_name:
            summary_parts.append(f"Customer: {self.customer_info.first_name}")
        
        if self.customer_info.company_name:
            summary_parts.append(f"Company: {self.customer_info.company_name}")
        
        # Business context
        if self.business_info.team_size:
            summary_parts.append(f"Team size: {self.business_info.team_size}")
        
        if self.business_info.pain_points:
            pain_points_str = ", ".join(self.business_info.pain_points[:3])
            summary_parts.append(f"Pain points: {pain_points_str}")
        
        # Qualification status
        summary_parts.append(f"Status: {self.qualification_data.status.value}")
        summary_parts.append(f"Stage: {self.conversation_stage.value}")
        summary_parts.append(f"Score: {self.qualification_data.score}")
        
        # Join and truncate if necessary
        summary = " | ".join(summary_parts)
        if len(summary) > max_length:
            summary = summary[:max_length-3] + "..."
        
        return summary
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert conversation state to dictionary for serialization."""
        return {
            'thread_id': self.thread_id,
            'customer_info': self.customer_info.to_dict(),
            'business_info': self.business_info.to_dict(),
            'qualification_data': self.qualification_data.to_dict(),
            'conversation_stage': self.conversation_stage.value,
            'last_activity': self.last_activity.isoformat(),
            'created_at': self.created_at.isoformat(),
            'context_summary': self.context_summary,
            'key_insights': self.key_insights,
            'next_actions': self.next_actions,
            'metrics': self.metrics.to_dict(),
            'wow_moment_delivered': self.wow_moment_delivered,
            'follow_up_scheduled': self.follow_up_scheduled,
            'needs_human_handoff': self.needs_human_handoff
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationState':
        """Create conversation state from dictionary."""
        # Create customer info
        customer_info = CustomerInfo.from_dict(data['customer_info'])
        
        # Create business info
        business_info = BusinessInfo.from_dict(data['business_info'])
        
        # Create qualification data
        qualification_data = QualificationData.from_dict(data['qualification_data'])
        
        # Create conversation state
        state = cls(
            thread_id=data['thread_id'],
            customer_info=customer_info,
            business_info=business_info,
            qualification_data=qualification_data
        )
        
        # Set additional fields
        state.conversation_stage = ConversationStage(data['conversation_stage'])
        state.last_activity = datetime.fromisoformat(data['last_activity'])
        state.created_at = datetime.fromisoformat(data['created_at'])
        state.context_summary = data.get('context_summary', '')
        state.key_insights = data.get('key_insights', [])
        state.next_actions = data.get('next_actions', [])
        state.metrics = ConversationMetrics.from_dict(data.get('metrics', {}))
        state.wow_moment_delivered = data.get('wow_moment_delivered', False)
        state.follow_up_scheduled = data.get('follow_up_scheduled', False)
        state.needs_human_handoff = data.get('needs_human_handoff', False)
        
        return state


class ConversationStateManager:
    """
    Manager for conversation states with persistent storage and memory optimization.
    
    Features:
    - SQLite-based persistent storage
    - Memory trimming and optimization
    - State caching for performance
    - Automatic cleanup of old conversations
    - Integration with LangGraph checkpointing
    """
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DATABASE_URL", "sqlite:///./conversation_states.db")
        if self.db_path.startswith("sqlite:///"):
            self.db_path = self.db_path[10:]  # Remove sqlite:/// prefix
        
        self.cache: Dict[str, ConversationState] = {}
        self.cache_max_size = 100
        self.cache_ttl = timedelta(hours=1)
        
        # Initialize database
        self._init_database()
        
        # Create LangGraph checkpointer
        self.checkpointer = SqliteSaver.from_conn_string(f"sqlite:///{self.db_path}")
        
        logger.info("ConversationStateManager initialized", db_path=self.db_path)
    
    def _init_database(self) -> None:
        """Initialize SQLite database for conversation states."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create conversation_states table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversation_states (
                    thread_id TEXT PRIMARY KEY,
                    state_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP,
                    qualification_status TEXT,
                    conversation_stage TEXT,
                    customer_email TEXT,
                    customer_phone TEXT
                )
            ''')
            
            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_activity ON conversation_states(last_activity)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_qualification_status ON conversation_states(qualification_status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_email ON conversation_states(customer_email)')
            
            conn.commit()
            conn.close()
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error("Error initializing database", error=str(e))
            raise
    
    def get_state(self, thread_id: str) -> Optional[ConversationState]:
        """Get conversation state by thread ID."""
        # Check cache first
        if thread_id in self.cache:
            cached_state = self.cache[thread_id]
            # Check if cache is still valid
            if datetime.utcnow() - cached_state.last_activity < self.cache_ttl:
                return cached_state
            else:
                # Remove expired cache entry
                del self.cache[thread_id]
        
        # Load from database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT state_data FROM conversation_states WHERE thread_id = ?',
                (thread_id,)
            )
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                state_data = json.loads(result[0])
                state = ConversationState.from_dict(state_data)
                
                # Add to cache
                self._add_to_cache(thread_id, state)
                
                return state
            
            return None
            
        except Exception as e:
            logger.error("Error loading conversation state", thread_id=thread_id, error=str(e))
            return None
    
    def save_state(self, state: ConversationState) -> bool:
        """Save conversation state to persistent storage."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            state_json = json.dumps(state.to_dict())
            
            cursor.execute('''
                INSERT OR REPLACE INTO conversation_states 
                (thread_id, state_data, updated_at, last_activity, qualification_status, 
                 conversation_stage, customer_email, customer_phone)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
            ''', (
                state.thread_id,
                state_json,
                state.last_activity.isoformat(),
                state.qualification_data.status.value,
                state.conversation_stage.value,
                state.customer_info.email,
                state.customer_info.phone
            ))
            
            conn.commit()
            conn.close()
            
            # Update cache
            self._add_to_cache(state.thread_id, state)
            
            logger.info("Conversation state saved", thread_id=state.thread_id)
            return True
            
        except Exception as e:
            logger.error("Error saving conversation state", thread_id=state.thread_id, error=str(e))
            return False
    
    def create_state(
        self,
        thread_id: str,
        contact_id: str,
        customer_data: Dict[str, Any]
    ) -> ConversationState:
        """Create a new conversation state."""
        customer_info = CustomerInfo(
            contact_id=contact_id,
            first_name=customer_data.get('firstName'),
            last_name=customer_data.get('lastName'),
            email=customer_data.get('email'),
            phone=customer_data.get('phone'),
            company_name=customer_data.get('companyName'),
            job_title=customer_data.get('jobTitle'),
            source=customer_data.get('source'),
            custom_fields=customer_data.get('customFields', {})
        )
        
        state = ConversationState(
            thread_id=thread_id,
            customer_info=customer_info
        )
        
        # Save to database
        self.save_state(state)
        
        logger.info("New conversation state created", thread_id=thread_id, contact_id=contact_id)
        return state
    
    def _add_to_cache(self, thread_id: str, state: ConversationState) -> None:
        """Add state to cache with size management."""
        # Remove oldest entries if cache is full
        if len(self.cache) >= self.cache_max_size:
            # Remove the oldest entry
            oldest_thread = min(self.cache.keys(), key=lambda k: self.cache[k].last_activity)
            del self.cache[oldest_thread]
        
        self.cache[thread_id] = state
    
    def cleanup_old_states(self, days_old: int = 30) -> int:
        """Clean up conversation states older than specified days."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM conversation_states WHERE last_activity < ?',
                (cutoff_date.isoformat(),)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info("Cleaned up old conversation states", deleted_count=deleted_count, days_old=days_old)
            return deleted_count
            
        except Exception as e:
            logger.error("Error cleaning up old states", error=str(e))
            return 0
    
    def get_checkpointer(self) -> BaseCheckpointSaver:
        """Get LangGraph checkpointer for persistent state management."""
        return self.checkpointer
    
    def get_active_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get list of active conversations with summary information."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT thread_id, qualification_status, conversation_stage, 
                       customer_email, last_activity, created_at
                FROM conversation_states 
                WHERE last_activity > datetime('now', '-7 days')
                ORDER BY last_activity DESC 
                LIMIT ?
            ''', (limit,))
            
            results = cursor.fetchall()
            conn.close()
            
            conversations = []
            for row in results:
                conversations.append({
                    'thread_id': row[0],
                    'qualification_status': row[1],
                    'conversation_stage': row[2],
                    'customer_email': row[3],
                    'last_activity': row[4],
                    'created_at': row[5]
                })
            
            return conversations
            
        except Exception as e:
            logger.error("Error getting active conversations", error=str(e))
            return []


# Global state manager instance
_state_manager = None


def get_state_manager() -> ConversationStateManager:
    """Get the global conversation state manager instance."""
    global _state_manager
    if _state_manager is None:
        _state_manager = ConversationStateManager()
    return _state_manager


def create_conversation_state(
    thread_id: str,
    contact_id: str,
    customer_data: Dict[str, Any]
) -> ConversationState:
    """
    Convenience function to create a new conversation state.
    
    Args:
        thread_id: Unique thread identifier
        contact_id: GHL contact ID
        customer_data: Customer information dictionary
        
    Returns:
        ConversationState: New conversation state instance
    """
    manager = get_state_manager()
    return manager.create_state(thread_id, contact_id, customer_data)


def get_conversation_state(thread_id: str) -> Optional[ConversationState]:
    """
    Convenience function to get conversation state by thread ID.
    
    Args:
        thread_id: Thread identifier
        
    Returns:
        Optional[ConversationState]: Conversation state if found
    """
    manager = get_state_manager()
    return manager.get_state(thread_id)


def save_conversation_state(state: ConversationState) -> bool:
    """
    Convenience function to save conversation state.
    
    Args:
        state: Conversation state to save
        
    Returns:
        bool: True if saved successfully
    """
    manager = get_state_manager()
    return manager.save_state(state)
