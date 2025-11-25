"""
Knowledge Layer - Structured Agent Learning System

Tracks discoveries, patterns, and lessons beyond thermodynamic governance metrics.
Complements behavior tracking (EISV) with knowledge accumulation.

Version: 1.0 (Minimal)
Created: 2025-11-24
Status: Experimental

Design Philosophy:
- Individual agents are fragile (sessions end)
- Knowledge should persist beyond sessions
- Discoveries are more valuable when queryable
- Complements existing notes/tags system
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import json
import sys


@dataclass
class Discovery:
    """
    A single discovery made by an agent.
    
    Discovery types:
    - "bug_found": System defect or vulnerability (can be resolved when fixed)
    - "insight": Understanding or realization (usually stays open)
    - "pattern": First observation of a recurring theme (if recurs, use log_pattern() instead)
    - "improvement": Enhancement or optimization (can be resolved when implemented)
    - "question": Complex open question with metadata (for simple questions, use add_question())
    
    Note: For recurring patterns (2+ occurrences), use log_pattern() instead of log_discovery(type="pattern").
    """
    timestamp: str
    type: str  # "bug_found", "insight", "pattern", "improvement", "question"
    summary: str
    details: str = ""
    severity: Optional[str] = None  # "low", "medium", "high", "critical"
    tags: List[str] = field(default_factory=list)
    status: str = "open"  # "open", "resolved", "archived"
    related_files: List[str] = field(default_factory=list)
    resolved_at: Optional[str] = None  # Timestamp when status changed to "resolved"
    related_discoveries: List[str] = field(default_factory=list)  # References to other discovery timestamps
    updated_at: Optional[str] = None  # Timestamp of last update

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pattern:
    """A behavioral or systemic pattern observed."""
    pattern_id: str
    description: str
    first_observed: str
    occurrences: int = 1
    severity: str = "medium"
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentKnowledge:
    """Complete knowledge record for an agent."""
    agent_id: str
    created_at: str
    last_updated: str
    discoveries: List[Discovery] = field(default_factory=list)
    patterns: List[Pattern] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)
    questions_raised: List[str] = field(default_factory=list)

    # Inheritance tracking (if spawned from parent)
    inherited_from: Optional[str] = None
    lineage: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "discoveries": [d.to_dict() for d in self.discoveries],
            "patterns": [p.to_dict() for p in self.patterns],
            "lessons_learned": self.lessons_learned,
            "questions_raised": self.questions_raised,
            "inherited_from": self.inherited_from,
            "lineage": self.lineage,
            "stats": {
                "total_discoveries": len(self.discoveries),
                "total_patterns": len(self.patterns),
                "total_lessons": len(self.lessons_learned),
                "total_questions": len(self.questions_raised)
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AgentKnowledge':
        """Load from dictionary."""
        # Convert discovery dicts back to Discovery objects
        discoveries = [Discovery(**d) for d in data.get("discoveries", [])]
        patterns = [Pattern(**p) for p in data.get("patterns", [])]

        return cls(
            agent_id=data["agent_id"],
            created_at=data["created_at"],
            last_updated=data["last_updated"],
            discoveries=discoveries,
            patterns=patterns,
            lessons_learned=data.get("lessons_learned", []),
            questions_raised=data.get("questions_raised", []),
            inherited_from=data.get("inherited_from"),
            lineage=data.get("lineage", [])
        )


class KnowledgeManager:
    """Manages agent knowledge storage and retrieval."""

    def __init__(self, data_dir: Path = None):
        if data_dir is None:
            # Default to governance-mcp-v1/data/knowledge/
            from pathlib import Path
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data" / "knowledge"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_knowledge_file(self, agent_id: str) -> Path:
        """Get path to knowledge file for agent."""
        return self.data_dir / f"{agent_id}_knowledge.json"

    def load_knowledge(self, agent_id: str) -> Optional[AgentKnowledge]:
        """Load knowledge for an agent, returns None if not found."""
        knowledge_file = self._get_knowledge_file(agent_id)

        if not knowledge_file.exists():
            return None

        try:
            with open(knowledge_file, 'r') as f:
                data = json.load(f)
                return AgentKnowledge.from_dict(data)
        except Exception as e:
            print(f"Warning: Could not load knowledge for {agent_id}: {e}", file=sys.stderr)
            return None

    def save_knowledge(self, knowledge: AgentKnowledge) -> None:
        """Save knowledge to disk."""
        knowledge_file = self._get_knowledge_file(knowledge.agent_id)

        # Update last_updated timestamp
        knowledge.last_updated = datetime.now().isoformat()

        with open(knowledge_file, 'w') as f:
            json.dump(knowledge.to_dict(), f, indent=2)

    def get_or_create_knowledge(self, agent_id: str) -> AgentKnowledge:
        """Get existing knowledge or create new record."""
        knowledge = self.load_knowledge(agent_id)

        if knowledge is None:
            now = datetime.now().isoformat()
            knowledge = AgentKnowledge(
                agent_id=agent_id,
                created_at=now,
                last_updated=now
            )

        return knowledge

    def log_discovery(
        self,
        agent_id: str,
        discovery_type: str,
        summary: str,
        details: str = "",
        severity: Optional[str] = None,
        tags: List[str] = None,
        related_files: List[str] = None
    ) -> Discovery:
        """Log a new discovery for an agent."""
        knowledge = self.get_or_create_knowledge(agent_id)

        discovery = Discovery(
            timestamp=datetime.now().isoformat(),
            type=discovery_type,
            summary=summary,
            details=details,
            severity=severity,
            tags=tags or [],
            related_files=related_files or []
        )

        knowledge.discoveries.append(discovery)
        self.save_knowledge(knowledge)

        return discovery

    def log_pattern(
        self,
        agent_id: str,
        pattern_id: str,
        description: str,
        severity: str = "medium",
        tags: List[str] = None,
        examples: List[str] = None
    ) -> Pattern:
        """Log a new pattern observation."""
        knowledge = self.get_or_create_knowledge(agent_id)

        # Check if pattern already exists
        existing = next((p for p in knowledge.patterns if p.pattern_id == pattern_id), None)

        if existing:
            # Increment occurrence count
            existing.occurrences += 1
            if examples:
                existing.examples.extend(examples)
            pattern = existing
        else:
            # Create new pattern
            pattern = Pattern(
                pattern_id=pattern_id,
                description=description,
                first_observed=datetime.now().isoformat(),
                severity=severity,
                tags=tags or [],
                examples=examples or []
            )
            knowledge.patterns.append(pattern)

        self.save_knowledge(knowledge)
        return pattern

    def add_lesson(self, agent_id: str, lesson: str) -> None:
        """
        Add a lesson learned (actionable takeaway).
        
        Use this for what worked, what didn't, or what to remember.
        For discrete events (bugs, insights), use log_discovery() instead.
        """
        knowledge = self.get_or_create_knowledge(agent_id)
        if lesson not in knowledge.lessons_learned:
            knowledge.lessons_learned.append(lesson)
            self.save_knowledge(knowledge)

    def add_question(self, agent_id: str, question: str) -> None:
        """
        Add an open question (simple format, no metadata).
        
        Use this for simple questions. For complex questions with severity/tags/files,
        use log_discovery(type="question") instead.
        """
        knowledge = self.get_or_create_knowledge(agent_id)
        if question not in knowledge.questions_raised:
            knowledge.questions_raised.append(question)
            self.save_knowledge(knowledge)

    def query_discoveries(
        self,
        agent_id: Optional[str] = None,
        discovery_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        search_text: Optional[str] = None,
        sort_by: str = "timestamp",  # "timestamp", "severity", "status"
        sort_order: str = "desc"  # "asc", "desc"
    ) -> List[Discovery]:
        """
        Query discoveries across agents with filters and full-text search.
        
        Args:
            agent_id: Filter by specific agent (None = all agents)
            discovery_type: Filter by type (bug_found, insight, etc.)
            tags: Filter by tags (OR matching - any tag matches)
            severity: Filter by severity level
            status: Filter by status (open, resolved, archived)
            search_text: Full-text search in summary and details (case-insensitive)
            sort_by: Sort field (timestamp, severity, status)
            sort_order: Sort direction (asc, desc)
        """
        results = []

        # Determine which agents to query
        if agent_id:
            agent_ids = [agent_id]
        else:
            # All agents with knowledge files
            agent_ids = [
                f.stem.replace("_knowledge", "")
                for f in self.data_dir.glob("*_knowledge.json")
            ]

        # Collect matching discoveries
        for aid in agent_ids:
            knowledge = self.load_knowledge(aid)
            if not knowledge:
                continue

            for discovery in knowledge.discoveries:
                # Apply filters
                if discovery_type and discovery.type != discovery_type:
                    continue
                if severity and discovery.severity != severity:
                    continue
                if status and discovery.status != status:
                    continue
                if tags and not any(t in discovery.tags for t in tags):
                    continue
                
                # Full-text search
                if search_text:
                    search_lower = search_text.lower()
                    summary_match = search_lower in discovery.summary.lower()
                    details_match = search_lower in discovery.details.lower()
                    if not (summary_match or details_match):
                        continue

                results.append(discovery)

        # Sorting
        if sort_by == "timestamp":
            results.sort(key=lambda d: d.timestamp, reverse=(sort_order == "desc"))
        elif sort_by == "severity":
            severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, None: 0}
            results.sort(key=lambda d: severity_order.get(d.severity, 0), reverse=(sort_order == "desc"))
        elif sort_by == "status":
            status_order = {"open": 2, "resolved": 1, "archived": 0}
            results.sort(key=lambda d: status_order.get(d.status, 0), reverse=(sort_order == "desc"))

        return results

    def update_discovery_status(
        self,
        agent_id: str,
        discovery_timestamp: str,
        new_status: str,
        resolved_reason: Optional[str] = None
    ) -> Optional[Discovery]:
        """
        Update the status of a discovery.
        
        Args:
            agent_id: Agent who owns the discovery
            discovery_timestamp: Timestamp of the discovery to update
            new_status: New status ("open", "resolved", "archived")
            resolved_reason: Optional reason/note for resolution (appended to details)
        
        Returns:
            Updated discovery or None if not found
        """
        knowledge = self.load_knowledge(agent_id)
        if not knowledge:
            return None

        # Find discovery by timestamp
        discovery = next((d for d in knowledge.discoveries if d.timestamp == discovery_timestamp), None)
        if not discovery:
            return None

        # Update status
        old_status = discovery.status
        discovery.status = new_status
        discovery.updated_at = datetime.now().isoformat()

        # If resolving, set resolved_at and optionally add reason
        if new_status == "resolved" and old_status != "resolved":
            discovery.resolved_at = discovery.updated_at
            if resolved_reason:
                discovery.details += f"\n\n[Resolved {discovery.resolved_at}] {resolved_reason}"

        self.save_knowledge(knowledge)
        return discovery

    def update_discovery(
        self,
        agent_id: str,
        discovery_timestamp: str,
        summary: Optional[str] = None,
        details: Optional[str] = None,
        severity: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
        related_files: Optional[List[str]] = None,
        append_details: bool = False
    ) -> Optional[Discovery]:
        """
        Update fields of a discovery.
        
        Args:
            agent_id: Agent who owns the discovery
            discovery_timestamp: Timestamp of the discovery to update
            summary: New summary (replaces existing)
            details: New details (replaces existing unless append_details=True)
            severity: New severity level
            tags: New tags list (replaces existing)
            status: New status
            related_files: New related files list (replaces existing)
            append_details: If True, append to details instead of replacing
        
        Returns:
            Updated discovery or None if not found
        """
        knowledge = self.load_knowledge(agent_id)
        if not knowledge:
            return None

        # Find discovery by timestamp
        discovery = next((d for d in knowledge.discoveries if d.timestamp == discovery_timestamp), None)
        if not discovery:
            return None

        # Update fields
        if summary is not None:
            discovery.summary = summary
        if details is not None:
            if append_details:
                discovery.details += f"\n\n[{datetime.now().isoformat()}] {details}"
            else:
                discovery.details = details
        if severity is not None:
            discovery.severity = severity
        if tags is not None:
            discovery.tags = tags
        if status is not None:
            old_status = discovery.status
            discovery.status = status
            if status == "resolved" and old_status != "resolved":
                discovery.resolved_at = datetime.now().isoformat()
        if related_files is not None:
            discovery.related_files = related_files

        discovery.updated_at = datetime.now().isoformat()
        self.save_knowledge(knowledge)
        return discovery

    def find_similar_discoveries(
        self,
        summary: str,
        threshold: float = 0.7,
        agent_id: Optional[str] = None
    ) -> List[Tuple[Discovery, float]]:
        """
        Find discoveries with similar summaries using simple text similarity.
        
        Args:
            summary: Summary text to compare against
            threshold: Similarity threshold (0.0-1.0), higher = more strict
            agent_id: Optional agent filter
        
        Returns:
            List of (discovery, similarity_score) tuples, sorted by similarity descending
        """
        from difflib import SequenceMatcher
        
        all_discoveries = self.query_discoveries(agent_id=agent_id)
        summary_lower = summary.lower()
        
        similar = []
        for discovery in all_discoveries:
            # Simple similarity using SequenceMatcher
            similarity = SequenceMatcher(None, summary_lower, discovery.summary.lower()).ratio()
            if similarity >= threshold:
                similar.append((discovery, similarity))
        
        # Sort by similarity descending
        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all agents."""
        all_knowledge = []
        for knowledge_file in self.data_dir.glob("*_knowledge.json"):
            agent_id = knowledge_file.stem.replace("_knowledge", "")
            knowledge = self.load_knowledge(agent_id)
            if knowledge:
                all_knowledge.append(knowledge)

        return {
            "total_agents": len(all_knowledge),
            "total_discoveries": sum(len(k.discoveries) for k in all_knowledge),
            "total_patterns": sum(len(k.patterns) for k in all_knowledge),
            "total_lessons": sum(len(k.lessons_learned) for k in all_knowledge),
            "total_questions": sum(len(k.questions_raised) for k in all_knowledge),
            "agents_with_knowledge": [k.agent_id for k in all_knowledge]
        }


# Global instance for convenience
_default_manager = None

def get_knowledge_manager() -> KnowledgeManager:
    """Get or create default knowledge manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = KnowledgeManager()
    return _default_manager


# Convenience functions
def log_discovery(agent_id: str, discovery_type: str, summary: str, **kwargs) -> Discovery:
    """Convenience function to log a discovery."""
    return get_knowledge_manager().log_discovery(agent_id, discovery_type, summary, **kwargs)

def log_pattern(agent_id: str, pattern_id: str, description: str, **kwargs) -> Pattern:
    """Convenience function to log a pattern."""
    return get_knowledge_manager().log_pattern(agent_id, pattern_id, description, **kwargs)

def add_lesson(agent_id: str, lesson: str) -> None:
    """Convenience function to add a lesson."""
    get_knowledge_manager().add_lesson(agent_id, lesson)

def add_question(agent_id: str, question: str) -> None:
    """Convenience function to add a question."""
    get_knowledge_manager().add_question(agent_id, question)

def get_knowledge(agent_id: str) -> Optional[AgentKnowledge]:
    """Convenience function to get agent knowledge."""
    return get_knowledge_manager().load_knowledge(agent_id)

def query_discoveries(**filters) -> List[Discovery]:
    """Convenience function to query discoveries."""
    return get_knowledge_manager().query_discoveries(**filters)

def update_discovery_status(agent_id: str, discovery_timestamp: str, new_status: str, resolved_reason: Optional[str] = None) -> Optional[Discovery]:
    """Convenience function to update discovery status."""
    return get_knowledge_manager().update_discovery_status(agent_id, discovery_timestamp, new_status, resolved_reason)

def update_discovery(agent_id: str, discovery_timestamp: str, **kwargs) -> Optional[Discovery]:
    """Convenience function to update discovery fields."""
    return get_knowledge_manager().update_discovery(agent_id, discovery_timestamp, **kwargs)

def find_similar_discoveries(summary: str, threshold: float = 0.7, agent_id: Optional[str] = None) -> List[Tuple[Discovery, float]]:
    """Convenience function to find similar discoveries."""
    return get_knowledge_manager().find_similar_discoveries(summary, threshold, agent_id)
