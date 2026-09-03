"""CLI entrypoint for Model Watcher single-run execution."""
import argparse
import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional

from model_watcher.aggregator import ModelAggregator
from model_watcher.config import DEFAULT_PROFILE_PATH, initialize_profile_interactive, load_profile
from model_watcher.evaluator import ModelEvaluator
from model_watcher.reporter import MarkdownReporter
from model_watcher.state import DEFAULT_STATE_PATH, load_state, save_state
from model_watcher.types import Role

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("model_watcher")


def run_watcher(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    reports_dir: Path = Path("reports"),
    target_model: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    quiet_on_empty: bool = True,
) -> int:
    """Executes single run: check new models -> eval -> report -> update state -> exit."""
    # 1. Read profile (or initialize if absent)
    if not profile_path.exists():
        print(f"[INIT] Profile not found at {profile_path}. Launching baseline initialization...")
        profile = initialize_profile_interactive(target_path=profile_path)
    else:
        try:
            profile = load_profile(profile_path)
        except Exception as e:
            print(f"[ERROR] Failed to load baseline profile from {profile_path}: {e}", file=sys.stderr)
            return 1

    # 2. Read state
    state = load_state(state_path)
    is_bootstrap = (len(state.models) == 0 and state.last_run is None)

    # 3. Discover candidates & check structured data sources
    aggregator = ModelAggregator()

    # Handle bootstrap when no specific model is targeted
    if is_bootstrap and not target_model:
        aggregator.get_pending_models(state, is_bootstrap=True)
        if not dry_run:
            save_state(state, state_path)
        print(
            f"[BOOTSTRAP] Initialized discovery state: recorded {len(state.models)} historical models as baseline. "
            f"0 unsolicited reports generated."
        )
        return 0

    pending = aggregator.get_pending_models(
        state,
        force_model=target_model,
        is_bootstrap=False,
    )

    # Save state if any unconfirmed models were marked as SEEN during discovery
    if not dry_run:
        save_state(state, state_path)

    if not pending:
        if not quiet_on_empty:
            print("No new models found and no provisional models due for re-evaluation. Up to date.")
        return 0

    evaluator = ModelEvaluator(profile)
    reporter = MarkdownReporter(reports_dir=reports_dir)

    for challenger in pending:
        # Collect comparative evidence for each of the 7 roles
        role_evaluations = {}
        all_evidence_bytes = []

        for role in Role:
            incumbent = profile.get_incumbent(role)
            evidence_list = aggregator.collect_role_evidence(
                challenger=challenger.canonical_id,
                incumbent=incumbent,
                role=role,
            )
            for ev in evidence_list:
                all_evidence_bytes.append(f"{ev.source}:{ev.benchmark}:{ev.score_challenger}:{ev.score_incumbent}".encode())

            role_eval = evaluator.evaluate_role(role, challenger, evidence_list)
            role_evaluations[role] = role_eval

        # Generate report
        report = evaluator.build_report(challenger, role_evaluations)
        report_path = reporter.save_report(report)

        # Print report to stdout
        formatted_md = reporter.format_report(report)
        print(formatted_md)
        print(f"\n[Report saved to: {report_path}]")

        # Update state
        if not dry_run:
            ev_hash = hashlib.sha256(b"".join(all_evidence_bytes)).hexdigest()[:16]
            state.record_evaluation(
                canonical_id=challenger.canonical_id,
                display_name=challenger.display_name,
                provider=challenger.provider,
                report_ref=str(report_path),
                release_date=challenger.release_date,
                release_confirmed=challenger.release_confirmed,
                evidence_hash=ev_hash,
            )
            save_state(state, state_path)

    return 0


def print_status(profile_path: Path, state_path: Path) -> None:
    print("=== Model Watcher Status ===")
    if profile_path.exists():
        try:
            profile = load_profile(profile_path)
            print(f"Profile: {profile_path} (Valid)")
            print(f"  User: {profile.user_name}")
            print(f"  Accessible Models: {', '.join(profile.accessible_models)}")
            print("  Baseline Routes:")
            for role in Role:
                print(f"    - {role.display_name}: {profile.get_incumbent(role)}")
        except Exception as e:
            print(f"Profile: {profile_path} (Invalid: {e})")
    else:
        print(f"Profile: {profile_path} (Missing)")

    if state_path.exists():
        state = load_state(state_path)
        print(f"\nState: {state_path}")
        print(f"  Last Run: {state.last_run or 'Never'}")
        print(f"  Tracked Models ({len(state.models)}):")
        seen_count = sum(1 for m in state.models.values() if m.status == "SEEN")
        provisional_count = sum(1 for m in state.models.values() if m.status == "PROVISIONAL")
        mature_count = sum(1 for m in state.models.values() if m.status == "MATURE")
        print(f"  Summary: {seen_count} historical/SEEN, {provisional_count} PROVISIONAL, {mature_count} MATURE")
        for m in list(state.models.values())[:10]:
            rel_info = f"rel: {m.release_date}" if m.release_date else "rel: unconfirmed"
            print(f"    - {m.canonical_id} [{m.status}] ({rel_info})")
        if len(state.models) > 10:
            print(f"    ... and {len(state.models) - 10} more models.")
    else:
        print(f"\nState: {state_path} (Empty/New)")


def main():
    parser = argparse.ArgumentParser(
        description="Model Watcher - Continuous Frontier AI Model Routing Monitor"
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run model check and evaluation cycle")
    run_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH, help="Path to profile.yaml")
    run_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Path to state.json")
    run_parser.add_argument("--reports", type=Path, default=Path("reports"), help="Directory for reports")
    run_parser.add_argument("--model", type=str, default=None, help="Target specific model ID to evaluate")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not update state.json")
    run_parser.add_argument("--force", action="store_true", help="Force re-evaluation even if mature/seen")
    run_parser.add_argument("--verbose", action="store_true", help="Verbose output even if no new models")

    init_parser = subparsers.add_parser("init", help="Initialize user baseline profile")
    init_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH, help="Path to profile.yaml")
    init_parser.add_argument("--defaults", action="store_true", help="Use default example values")

    status_parser = subparsers.add_parser("status", help="Show current profile and state status")
    status_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH, help="Path to profile.yaml")
    status_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Path to state.json")

    args = parser.parse_args()

    cmd = args.command or "run"
    if cmd == "init":
        initialize_profile_interactive(target_path=args.profile, use_defaults=args.defaults)
    elif cmd == "status":
        print_status(args.profile, args.state)
    elif cmd == "run":
        prof = getattr(args, "profile", DEFAULT_PROFILE_PATH)
        st = getattr(args, "state", DEFAULT_STATE_PATH)
        rep = getattr(args, "reports", Path("reports"))
        model = getattr(args, "model", None)
        dry = getattr(args, "dry_run", False)
        force = getattr(args, "force", False)
        verbose = getattr(args, "verbose", False)

        code = run_watcher(
            profile_path=prof,
            state_path=st,
            reports_dir=rep,
            target_model=model,
            dry_run=dry,
            force=force,
            quiet_on_empty=not verbose,
        )
        sys.exit(code)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
