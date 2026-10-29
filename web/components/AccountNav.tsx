"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Account, currentAccount, isAuthConfigured, signOut } from "@/lib/auth";

const navLink =
  "whitespace-nowrap rounded-[3px] px-1.5 py-2 text-[14px] text-ink-muted underline-offset-4 hover:text-ink hover:underline sm:px-2";

/** "Sign in", or the signed-in email with "Sign out". */
export function AccountNav({ initial }: { initial?: Account | null }) {
  const [account, setAccount] = useState<Account | null | undefined>(initial);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (initial !== undefined || !isAuthConfigured) return;
    let live = true;
    currentAccount().then((a) => live && setAccount(a));
    return () => {
      live = false;
    };
  }, [initial]);

  if (!account) {
    return (
      <Link href="/login" className={navLink}>
        Sign in
      </Link>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <span className="hidden max-w-[180px] truncate text-[13px] text-ink-muted lg:inline" title={account.email}>
        {account.email}
      </span>
      <button
        type="button"
        disabled={busy}
        className={navLink}
        onClick={async () => {
          setBusy(true);
          try {
            await signOut();
          } finally {
            // Full page load on purpose: the server must see the changed sign-in cookie.
            // eslint-disable-next-line @next/next/no-location-assign-relative-destination
            window.location.assign("/");
          }
        }}
      >
        Sign out
      </button>
    </span>
  );
}
