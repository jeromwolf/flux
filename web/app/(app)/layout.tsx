"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { getMe, logout } from "@/lib/api";
import { Logo } from "@/components/Logo";

export default function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: user, isLoading, isError } = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
  });

  useEffect(() => {
    if (!isLoading && (isError || user === null)) {
      router.replace("/login");
    }
  }, [isLoading, isError, user, router]);

  if (isLoading || !user) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-zinc-500">
        Loading…
      </div>
    );
  }

  return (
    <div className="grid min-h-screen grid-cols-[220px_1fr]">
      <aside className="flex flex-col gap-1 border-r border-border-base bg-bg-subtle p-4">
        <div className="mb-6 px-2 pt-1"><Logo /></div>
        <NavLink href="/dashboard">Agents</NavLink>

        <div className="mt-auto flex items-center gap-3 border-t border-border-base pt-4">
          {user.avatar_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full border border-border-base" />
          )}
          <div className="min-w-0 flex-1 text-xs">
            <div className="truncate font-medium text-zinc-100">{user.github_login}</div>
            <button
              type="button"
              className="text-zinc-500 hover:text-zinc-300"
              onClick={async () => {
                await logout();
                router.replace("/");
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="px-8 py-8">{children}</main>
    </div>
  );
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-md px-2.5 py-1.5 text-sm text-zinc-300 hover:bg-bg-elevated hover:text-zinc-100"
    >
      {children}
    </Link>
  );
}
