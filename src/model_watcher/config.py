"""User baseline profile and configuration handling."""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from model_watcher.types import Role


@dataclass
class RoleRouting:
    primary: str
    fallback: Optional[str] = None
    notes: str = ""


@dataclass
class UserProfile:
    version: str
    user_name: str
    accessible_models: List[str]
    cost_sensitive: bool
    preferred_providers: List[str]
    monthly_budget_usd: Optional[float]
    routing: Dict[Role, RoleRouting]
    raw_yaml: Dict[str, Any] = field(default_factory=dict)

    def get_incumbent(self, role: Role) -> str:
        if role in self.routing:
            return self.routing[role].primary
        return "unknown-incumbent"

    def is_accessible(self, model_name: str) -> bool:
        normalized = model_name.lower().strip()
        return any(normalized in m.lower() or m.lower() in normalized for m in self.accessible_models)


DEFAULT_PROFILE_PATH = Path("profile.yaml")
EXAMPLE_PROFILE_PATH = Path("profile.yaml.example")


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> UserProfile:
    """Load profile from disk. Does not modify the file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Baseline profile not found at {path}. Run initialization flow first."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid profile format in {path}: expected a YAML mapping.")

    user_info = data.get("user", {})
    constraints = user_info.get("constraints", {})
    routing_data = data.get("baseline_routing", {})

    routing: Dict[Role, RoleRouting] = {}
    for role in Role:
        role_key = role.value
        if role_key in routing_data:
            entry = routing_data[role_key]
            routing[role] = RoleRouting(
                primary=str(entry.get("primary", "")).strip(),
                fallback=entry.get("fallback"),
                notes=entry.get("notes", ""),
            )
        else:
            raise ValueError(f"Missing required role routing for '{role_key}' in {path}")

    return UserProfile(
        version=str(data.get("version", "1.0")),
        user_name=str(user_info.get("name", "User")),
        accessible_models=list(user_info.get("accessible_models", [])),
        cost_sensitive=bool(constraints.get("cost_sensitive", True)),
        preferred_providers=list(constraints.get("preferred_providers", [])),
        monthly_budget_usd=constraints.get("monthly_budget_usd"),
        routing=routing,
        raw_yaml=data,
    )


def initialize_profile_interactive(
    target_path: Path = DEFAULT_PROFILE_PATH,
    use_defaults: bool = False,
    input_func=input,
) -> UserProfile:
    """Interactive baseline establishment, asking one necessary question at a time."""
    if target_path.exists():
        print(f"Profile already exists at {target_path}. Retaining existing profile without modification.")
        return load_profile(target_path)

    print("==================================================")
    print("      Model Watcher Baseline Initialization       ")
    print("==================================================")
    print("Establishing user model usage baseline...")

    if use_defaults or not sys.stdin.isatty():
        print("Non-interactive mode or --defaults specified; initializing with standard baseline.")
        # Load from example
        if EXAMPLE_PROFILE_PATH.exists():
            with open(EXAMPLE_PROFILE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = _generate_default_yaml()
    else:
        # Ask one question at a time
        print("\nQ1: What models do you currently have access to? (comma-separated)")
        models_input = input_func("Accessible models [claude-3-7-sonnet, gpt-4o, o3-mini, gemini-2.5-pro, deepseek-v3]: ").strip()
        models = [m.strip() for m in models_input.split(",") if m.strip()] if models_input else [
            "claude-3-7-sonnet", "gpt-4o", "o3-mini", "gemini-2.5-pro", "deepseek-v3"
        ]

        print("\nQ2: Are you sensitive to API / token cost? (y/n)")
        cost_input = input_func("Cost sensitive [y]: ").strip().lower()
        cost_sensitive = cost_input != "n"

        routing_answers = {}
        for role in Role:
            print(f"\nRole routing for: {role.display_name}")
            def_primary = "o3-mini" if role == Role.REASONER else ("gemini-2.5-pro" if role == Role.MULTIMODAL else "claude-3-7-sonnet")
            primary = input_func(f"  Primary incumbent [{def_primary}]: ").strip() or def_primary
            fallback = input_func(f"  Fallback incumbent (optional): ").strip() or None
            routing_answers[role.value] = {"primary": primary, "fallback": fallback, "notes": f"Initial {role.display_name} incumbent"}

        data = {
            "version": "1.0",
            "user": {
                "name": "User",
                "accessible_models": models,
                "constraints": {
                    "cost_sensitive": cost_sensitive,
                    "preferred_providers": ["anthropic", "openai", "google"],
                    "monthly_budget_usd": None,
                },
            },
            "baseline_routing": routing_answers,
        }
        content = yaml.dump(data, sort_keys=False, allow_unicode=True)

    # Write atomically
    temp_file = target_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_file, target_path)

    print(f"\n[OK] Baseline profile successfully established and saved to: {target_path}")
    return load_profile(target_path)


def _generate_default_yaml() -> str:
    data = {
        "version": "1.0",
        "user": {
            "name": "User",
            "accessible_models": [
                "claude-3-7-sonnet",
                "claude-opus-4-6",
                "gpt-4o",
                "o3-mini",
                "gemini-2.5-pro",
                "deepseek-v3",
            ],
            "constraints": {
                "cost_sensitive": True,
                "allow_subagents_cheap_models": True,
                "preferred_providers": ["anthropic", "openai", "google"],
                "monthly_budget_usd": None,
            },
        },
        "baseline_routing": {
            "coder": {"primary": "claude-3-7-sonnet", "fallback": "gpt-4o", "notes": "Repo coding and debugging"},
            "planner": {"primary": "claude-3-7-sonnet", "fallback": "o3-mini", "notes": "Architecture and planning"},
            "reviewer": {"primary": "claude-3-7-sonnet", "fallback": "o3-mini", "notes": "Adversarial code review"},
            "reasoner": {"primary": "o3-mini", "fallback": "claude-3-7-sonnet", "notes": "Math and logic"},
            "analyst": {"primary": "claude-3-7-sonnet", "fallback": "gemini-2.5-pro", "notes": "Research and data analysis"},
            "agent": {"primary": "claude-3-7-sonnet", "fallback": "gpt-4o", "notes": "Terminal and tool execution"},
            "multimodal": {"primary": "gemini-2.5-pro", "fallback": "claude-3-7-sonnet", "notes": "Multimodal tasks"},
        },
    }
    return yaml.dump(data, sort_keys=False, allow_unicode=True)
