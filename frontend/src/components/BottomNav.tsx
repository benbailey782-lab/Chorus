import { NavLink } from "react-router-dom";

// Minimalist inline SVG set so we don't pull in an icon library.
function Icon({ d }: { d: string }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

const TABS = [
  { to: "/", label: "Library", icon: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" },
  { to: "/voices", label: "Voices", icon: "M12 3v12m-4-8v4m8-6v8m-12 0v2m16-2v2" },
  { to: "/player", label: "Player", icon: "M8 5v14l11-7z" },
  { to: "/settings", label: "Settings", icon: "M12 8a4 4 0 100 8 4 4 0 000-8zm8 4a8 8 0 01-.17 1.7l2.1 1.63-2 3.46-2.47-1a8 8 0 01-2.94 1.7L14 22h-4l-.52-2.5a8 8 0 01-2.94-1.7l-2.47 1-2-3.46 2.1-1.63A8 8 0 014 12a8 8 0 01.17-1.7L2.07 8.67l2-3.46 2.47 1A8 8 0 019.48 4.5L10 2h4l.52 2.5a8 8 0 012.94 1.7l2.47-1 2 3.46-2.1 1.63c.11.55.17 1.12.17 1.71z" },
];

export default function BottomNav() {
  return (
    <nav
      aria-label="Primary"
      className="fixed bottom-0 inset-x-0 z-20 border-t border-border bg-bg/95 backdrop-blur
                 md:static md:border-t-0 md:bg-transparent md:backdrop-blur-0"
      style={{ paddingBottom: "var(--safe-bottom, 0px)" }}
    >
      <ul className="max-w-5xl mx-auto grid grid-cols-4 md:flex md:justify-end md:gap-2">
        {TABS.map((t) => (
          <li key={t.to} className="md:flex-none">
            <NavLink
              to={t.to}
              end={t.to === "/"}
              className={({ isActive }) =>
                [
                  "flex flex-col items-center justify-center gap-0.5 min-h-tap px-2 py-1",
                  "md:flex-row md:gap-2 md:px-3 md:py-2 md:rounded-card",
                  isActive
                    ? "text-accent md:bg-surface-2"
                    : "text-muted hover:text-fg",
                ].join(" ")
              }
            >
              <Icon d={t.icon} />
              <span className="text-[11px] md:text-sm">{t.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
