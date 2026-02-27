"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { label: "Events", href: "/events" },
  { label: "Stocks", href: "/stocks" },
  { label: "Reports", href: "/reports" },
];

export function TabNav() {
  const pathname = usePathname();

  return (
    <nav className="mx-auto flex max-w-6xl gap-6 px-6">
      {tabs.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`border-b-2 pb-2 text-sm font-medium transition-colors ${
              active
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
