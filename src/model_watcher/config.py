"""User baseline profile and configuration handling with formal Calibration Lifecycle."""
from datetime import datetime, timezone
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import yaml

from model_watcher.types import NeedsCalibrationError, Role


@dataclass
class RoleRouting:
    primary: str
    fallback: Optional[str] = None
    notes: str = ""


@dataclass
class UserProfile:
    version: str
    revision: int
    calibrated_at: str
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
        raise NeedsCalibrationError(
            f"Baseline profile not found at {path}. Model Watcher requires an established baseline calibration before evaluating models. Please run './bin/model-watcher calibrate' first."
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
        revision=int(data.get("revision", 1)),
        calibrated_at=str(data.get("calibrated_at") or ""),
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
    """Interactive baseline establishment, asking necessary questions one at a time."""
    if target_path.exists():
        print(f"Profile already exists at {target_path}. Retaining existing profile without modification.")
        return load_profile(target_path)

    print("==================================================")
    print("      Model Watcher Baseline Initialization       ")
    print("==================================================")
    print("Establishing user model usage baseline...")

    now_iso = datetime.now(timezone.utc).isoformat()

    if use_defaults:
        content = _generate_default_yaml(revision=1, calibrated_at=now_iso)
    elif not sys.stdin.isatty():
        raise NeedsCalibrationError(
            f"Non-interactive execution detected without an existing profile at '{target_path}'. "
            "Model Watcher cannot evaluate models or suggest replacements without knowing your active baseline. "
            "Please run './bin/model-watcher calibrate' or './bin/model-watcher init' interactively to establish your baseline."
        )
    else:
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
            fallback = input_func("  Fallback incumbent (optional): ").strip() or None
            routing_answers[role.value] = {"primary": primary, "fallback": fallback, "notes": f"Initial {role.display_name} incumbent"}

        data = {
            "version": "1.0",
            "revision": 1,
            "calibrated_at": now_iso,
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

    temp_file = target_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_file, target_path)

    print(f"\n[OK] Baseline profile successfully established and saved to: {target_path}")
    return load_profile(target_path)


def recalibrate_profile_interactive(
    target_path: Path = DEFAULT_PROFILE_PATH,
    input_func=input,
) -> UserProfile:
    """Guided recalibration flow when user's active model division changes."""
    if not target_path.exists():
        print(f"[INIT] Profile not found at {target_path}. Directing to initial calibration...")
        return initialize_profile_interactive(target_path=target_path, input_func=input_func)

    current = load_profile(target_path)

    print("==================================================")
    print("         Model Watcher Baseline Recalibration      ")
    print("==================================================")
    print(f"Current Calibration: Revision {current.revision} (Calibrated at: {current.calibrated_at or 'Initial'})")
    print(f"Current Accessible Models: {', '.join(current.accessible_models)}")
    print("Current Baseline Routing:")
    for role in Role:
        inc = current.get_incumbent(role)
        fb = current.routing[role].fallback if role in current.routing and current.routing[role].fallback else "None"
        print(f"  - {role.display_name}: {inc} (fallback: {fb})")
    print("--------------------------------------------------")

    # 1. Update accessible models
    print("\nQ1: What models do you currently have access to? (comma-separated, Enter to keep current)")
    old_acc_str = ", ".join(current.accessible_models)
    models_in = input_func(f"Accessible models [{old_acc_str}]: ").strip()
    if models_in:
        new_accessible = [m.strip() for m in models_in.split(",") if m.strip()]
    else:
        new_accessible = list(current.accessible_models)

    # 2. Update 7-role baseline routing
    print("\nQ2: Review 7-Role Routing (press Enter to retain existing primary model):")
    new_routing = {}
    changes = []

    for role in Role:
        curr_primary = current.get_incumbent(role)
        curr_fallback = current.routing[role].fallback if role in current.routing else None

        ans = input_func(f"  {role.display_name} primary [{curr_primary}]: ").strip()
        new_primary = ans if ans else curr_primary

        ans_fb = input_func(f"  {role.display_name} fallback [{curr_fallback or 'None'}]: ").strip()
        new_fallback = ans_fb if ans_fb else curr_fallback

        new_routing[role.value] = {
            "primary": new_primary,
            "fallback": new_fallback,
            "notes": f"Calibrated {role.display_name} incumbent",
        }

        if new_primary != curr_primary:
            changes.append(f"{role.display_name}: {curr_primary} -> {new_primary}")
        else:
            changes.append(f"{role.display_name}: {curr_primary} (unchanged)")

    # 3. Show calibration diff
    print("\n================ Proposed Calibration Diff ================")
    print(f"Revision: {current.revision} -> {current.revision + 1}")
    print(f"Accessible Models: {current.accessible_models} -> {new_accessible}")
    print("Role Routings:")
    for c in changes:
        print(f"  - {c}")
    print("===========================================================")

    # 4. Explicit confirmation
    confirm = input_func("Confirm and apply this calibration? (y/N): ").strip().lower()
    if confirm not in ("y", "yes"):
        print("\n[CANCELLED] Recalibration aborted by user. Profile remains byte-for-byte unchanged.")
        return current

    # 5. Apply atomically
    new_revision = current.revision + 1
    new_calibrated_at = datetime.now(timezone.utc).isoformat()

    new_data = {
        "version": current.version,
        "revision": new_revision,
        "calibrated_at": new_calibrated_at,
        "user": {
            "name": current.user_name,
            "accessible_models": new_accessible,
            "constraints": {
                "cost_sensitive": current.cost_sensitive,
                "preferred_providers": current.preferred_providers,
                "monthly_budget_usd": current.monthly_budget_usd,
            },
        },
        "baseline_routing": new_routing,
    }
    content = yaml.dump(new_data, sort_keys=False, allow_unicode=True)

    temp_file = target_path.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_file, target_path)

    print(f"\n[OK] Baseline successfully recalibrated to Revision {new_revision} at {new_calibrated_at}!")
    return load_profile(target_path)


def _generate_default_yaml(revision: int = 1, calibrated_at: Optional[str] = None) -> str:
    now_iso = calibrated_at or datetime.now(timezone.utc).isoformat()
    data = {
        "version": "1.0",
        "revision": revision,
        "calibrated_at": now_iso,
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
