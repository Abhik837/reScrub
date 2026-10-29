"""Manage reScrub accounts from the command line. People can also create their own member accounts
on the website's sign-up page (POST /auth/register) unless ALLOW_REGISTRATION=false.

    python -m rescrub.accounts add someone@school.edu [--admin]   # prints a generated password
    python -m rescrub.accounts reset someone@school.edu            # new password, signs them out everywhere
    python -m rescrub.accounts disable someone@school.edu          # blocks sign-in, ends their sessions
    python -m rescrub.accounts enable someone@school.edu
    python -m rescrub.accounts list
    python -m rescrub.accounts ensure admin@example.com            # admin, only if missing (local Docker stack)
    python -m rescrub.accounts delete someone@school.edu           # account + all their recordings and files

On the web server: docker compose --profile api run --rm api python -m rescrub.accounts add ...
Give each person their password over a private channel. There is no self-service password change
or reset (no email service), so use `reset` when needed.
"""

import argparse
import getpass
import secrets
import sys

from . import auth, db
from .settings import get_settings
from .storage import get_storage


def new_password() -> str:
    return secrets.token_urlsafe(15)  # 20 characters, ~120 bits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("email")
    add.add_argument("--admin", action="store_true")
    add.add_argument("--ask", action="store_true", help="type the password instead of generating one")
    for name in ("reset", "disable", "enable"):
        p = sub.add_parser(name)
        p.add_argument("email")
        if name == "reset":
            p.add_argument("--ask", action="store_true")
    ensure = sub.add_parser("ensure", help="create an admin with a generated password unless the account exists")
    ensure.add_argument("email")
    sub.add_parser("list")
    delete = sub.add_parser("delete")
    delete.add_argument("email")
    delete.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = ap.parse_args()

    pool = db.connect(get_settings().database_url, max_size=1)

    def password(ask: bool) -> str:
        if not ask:
            return new_password()
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords don't match.")
        return pw

    try:
        if args.cmd == "ensure":
            email = auth.normalize_email(args.email)
            if any(u["email"] == email for u in auth.list_users(pool)):
                print(f"{email} already has an account.")
            else:
                pw = new_password()
                auth.create_user(pool, email, pw, "admin")
                print(f"Created admin {email}\nPassword: {pw}")
        elif args.cmd == "add":
            pw = password(args.ask)
            auth.create_user(pool, args.email, pw, "admin" if args.admin else "member")
            print(f"Created {auth.normalize_email(args.email)}" + ("" if args.ask else f"\nPassword: {pw}"))
        elif args.cmd == "reset":
            pw = password(args.ask)
            if not auth.set_password(pool, args.email, pw):
                sys.exit("No such account.")
            print("Password changed; all their sign-ins were ended." + ("" if args.ask else f"\nPassword: {pw}"))
        elif args.cmd in ("disable", "enable"):
            if not auth.set_disabled(pool, args.email, args.cmd == "disable"):
                sys.exit("No such account.")
            print(f"{args.cmd}d {auth.normalize_email(args.email)}")
        elif args.cmd == "delete":
            email = auth.normalize_email(args.email)
            with pool.connection() as c:
                user = c.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
            if user is None:
                sys.exit("No such account.")
            sids = db.session_ids_for_owner(pool, user["id"])
            if not args.yes and input(f"Delete {email} and {len(sids)} recording(s)? Type DELETE: ") != "DELETE":
                sys.exit("Not deleted.")
            storage = get_storage(get_settings())
            for sid in sids:
                for key in db.delete_session(pool, sid):
                    storage.delete(key)
            with pool.connection() as c:
                c.execute("DELETE FROM users WHERE id = %s", (user["id"],))
            print(f"Deleted {email} and {len(sids)} recording(s).")
        else:
            for u in auth.list_users(pool):
                state = "disabled" if u["disabled"] else "active"
                last = u["last_login_at"].strftime("%Y-%m-%d") if u["last_login_at"] else "never"
                print(f"{u['email']:40} {u['role']:7} {state:8} last sign-in {last}")
    except ValueError as e:
        sys.exit(str(e))
    except Exception as e:  # e.g. duplicate email
        if "unique" in str(e).lower():
            sys.exit("That email already has an account.")
        raise
    finally:
        pool.close()


if __name__ == "__main__":
    main()
