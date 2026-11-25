"""Independent GitHub/Copilot device login. Never reads other agents' credentials or prints tokens."""
import argparse
import json
import sys

from ..common import auth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Start GitHub browser device authorization")
    login.add_argument("--no-browser", action="store_true")
    login.add_argument("--wait", action="store_true", help="Poll after printing the browser code; useful in a terminal")
    login.add_argument("--allow-network", action="store_true")
    complete = commands.add_parser("complete", help="Complete a previously started device authorization")
    complete.add_argument("--timeout", type=int, default=180)
    complete.add_argument("--allow-network", action="store_true")
    status = commands.add_parser("status", help="Show local metadata, never the credentials")
    status.add_argument("--check", action="store_true", help="Verify model-directory access without inference")
    status.add_argument("--allow-network", action="store_true")
    commands.add_parser("logout", help="Delete only this project's saved credentials; other agents are unaffected")
    args = parser.parse_args()
    if (args.command in ("login", "complete") or getattr(args, "check", False)) and not args.allow_network:
        parser.error("Authentication/verification requires --allow-network")
    try:
        if args.command == "login":
            result = auth.start_device_login(open_browser=not args.no_browser)
            if args.wait:
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                result = auth.complete_device_login()
        elif args.command == "complete":
            result = auth.complete_device_login(timeout=args.timeout)
        elif args.command == "logout":
            auth.logout()
            result = {"removed": True, "other_agents_changed": False}
        else:
            result = auth.check_access() if args.check else auth.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except auth.AuthenticationError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, TypeError):
        # Do not expose malformed secret JSON, subprocess output, or provider bodies.
        print("Authentication failed: invalid local state or filesystem operation", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
