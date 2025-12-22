"""Thompson Bandit for A/B testing prompts"""
import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Arm:
    """Represents a bandit arm (prompt variant)"""
    arm_id: str
    stage: str  # 'code' or 'insights'
    prompt_version: str  # 'v1' or 'v2'
    description: str = ""


@dataclass
class ArmStats:
    """Statistics for a bandit arm"""
    alpha: float = 1.0  # successes + prior (Beta distribution)
    beta: float = 1.0   # failures + prior
    pulls: int = 0
    
    @property
    def success_rate(self) -> float:
        """Estimated success rate"""
        if self.pulls == 0:
            return 0.5
        return (self.alpha - 1) / max(self.pulls, 1)
    
    @property
    def expected_value(self) -> float:
        """Expected value (mean of Beta distribution)"""
        return self.alpha / (self.alpha + self.beta)


class ThompsonBandit:
    """
    Thompson Sampling for Bernoulli rewards (thumbs up/down).
    Each arm has Beta(alpha, beta). We sample p ~ Beta(alpha, beta) and choose max.
    """
    
    def __init__(self, state_path: str = "uploads/bandit_state.json"):
        self.state_path = state_path
        self._stats: Dict[str, ArmStats] = {}
        self._last_selections: Dict[str, str] = {}  # stage -> arm_id for current request
        self._load()
    
    def _load(self) -> None:
        """Load bandit state from disk"""
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for arm_id, s in raw.get('stats', {}).items():
                self._stats[arm_id] = ArmStats(
                    alpha=float(s.get('alpha', 1.0)),
                    beta=float(s.get('beta', 1.0)),
                    pulls=int(s.get('pulls', 0)),
                )
        except Exception:
            self._stats = {}
    
    def _save(self) -> None:
        """Save bandit state to disk"""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            raw = {
                'stats': {
                    arm_id: {
                        'alpha': s.alpha,
                        'beta': s.beta,
                        'pulls': s.pulls
                    }
                    for arm_id, s in self._stats.items()
                }
            }
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(raw, f, indent=2)
        except Exception:
            pass
    
    def ensure_arms(self, arms: List[Arm]) -> None:
        """Ensure all arms are registered in stats"""
        changed = False
        for arm in arms:
            if arm.arm_id not in self._stats:
                self._stats[arm.arm_id] = ArmStats()
                changed = True
        if changed:
            self._save()
    
    def choose(self, stage: str, arms: List[Arm]) -> Arm:
        """
        Choose an arm using Thompson Sampling.
        Returns the arm with the highest sampled value.
        """
        stage_arms = [a for a in arms if a.stage == stage]
        if not stage_arms:
            raise RuntimeError(f"No arms configured for stage '{stage}'")
        
        best_arm = None
        best_sample = -1.0
        
        for arm in stage_arms:
            s = self._stats.get(arm.arm_id, ArmStats())
            # Sample from Beta distribution
            sample = random.betavariate(s.alpha, s.beta)
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        
        if best_arm is None:
            best_arm = stage_arms[0]
        
        # Track selection for this request
        self._last_selections[stage] = best_arm.arm_id
        
        return best_arm
    
    def update(self, arm_id: str, reward: int) -> Optional[ArmStats]:
        """
        Update arm statistics based on feedback.
        reward: 1 for thumbs up, 0 for thumbs down
        """
        if arm_id not in self._stats:
            self._stats[arm_id] = ArmStats()
        
        s = self._stats[arm_id]
        s.pulls += 1
        if reward == 1:
            s.alpha += 1.0
        else:
            s.beta += 1.0
        
        self._save()
        return s
    
    def get_stats(self, arm_id: str) -> Optional[ArmStats]:
        """Get statistics for a specific arm"""
        return self._stats.get(arm_id)
    
    def get_all_stats(self) -> Dict[str, ArmStats]:
        """Get all arm statistics"""
        return self._stats.copy()
    
    def get_last_selection(self, stage: str) -> Optional[str]:
        """Get the last selected arm_id for a stage"""
        return self._last_selections.get(stage)
    
    def reset(self) -> None:
        """Reset all statistics"""
        self._stats.clear()
        self._last_selections.clear()
        try:
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
        except Exception:
            pass


# Define arms for code generation
CODE_ARMS = [
    Arm(
        arm_id="code_v1",
        stage="code",
        prompt_version="v1",
        description="Baseline code generation prompt"
    ),
    Arm(
        arm_id="code_v2",
        stage="code",
        prompt_version="v2",
        description="Enhanced code generation prompt with stricter rules"
    ),
]

# Define arms for insights generation
INSIGHTS_ARMS = [
    Arm(
        arm_id="insights_v1",
        stage="insights",
        prompt_version="v1",
        description="Baseline insights prompt"
    ),
    Arm(
        arm_id="insights_v2",
        stage="insights",
        prompt_version="v2",
        description="Enhanced insights prompt with more structure"
    ),
]

# Global bandit instance
bandit = ThompsonBandit()
bandit.ensure_arms(CODE_ARMS + INSIGHTS_ARMS)
