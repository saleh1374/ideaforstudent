import type { SVGProps } from "react";

/** Inline SVG icon set — no external icon library. RTL-safe stroke icons. */

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/* ——— nav ——— */
export const IconHome = (p: P) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5.5 9.5V20a1 1 0 0 0 1 1H10v-5.5h4V21h3.5a1 1 0 0 0 1-1V9.5" />
  </Svg>
);

export const IconTasks = (p: P) => (
  <Svg {...p}>
    <rect x="3.5" y="4" width="17" height="16" rx="3" />
    <path d="m8 12.5 2.2 2.2L15.5 9.5" />
    <path d="M8 7.5h8" />
  </Svg>
);

export const IconBook = (p: P) => (
  <Svg {...p}>
    <path d="M12 6.5C10.5 5 8.6 4.4 5.5 4.4c-.8 0-1.5.6-1.5 1.4v11.4c0 .8.7 1.4 1.5 1.4 3.1 0 5 .6 6.5 2.1 1.5-1.5 3.4-2.1 6.5-2.1.8 0 1.5-.6 1.5-1.4V5.8c0-.8-.7-1.4-1.5-1.4-3.1 0-5 .6-6.5 2.1Z" />
    <path d="M12 6.5v15.7" />
  </Svg>
);

export const IconAlert = (p: P) => (
  <Svg {...p}>
    <path d="M10.3 4.2 2.8 17.4c-.7 1.3.2 2.9 1.7 2.9h15c1.4 0 2.4-1.6 1.7-2.9L13.7 4.2c-.7-1.3-2.4-1.3-3.1 0Z" />
    <path d="M12 9.5v4" />
    <path d="M12 17h.01" />
  </Svg>
);

export const IconExam = (p: P) => (
  <Svg {...p}>
    <rect x="5" y="3.5" width="14" height="17" rx="2.5" />
    <path d="M9 3.5V6a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1V3.5" />
    <path d="M8.5 11h7M8.5 15h4.5" />
  </Svg>
);

export const IconSparkles = (p: P) => (
  <Svg {...p}>
    <path d="M12 3.5 13.6 8a1.7 1.7 0 0 0 1 1L19 10.5 14.6 12a1.7 1.7 0 0 0-1 1l-1.6 4.5L10.4 13a1.7 1.7 0 0 0-1-1L5 10.5 9.4 9a1.7 1.7 0 0 0 1-1Z" />
    <path d="M18.5 16.5v3.5M16.75 18.25h3.5" />
  </Svg>
);

export const IconChart = (p: P) => (
  <Svg {...p}>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <rect x="7.5" y="12" width="3" height="5" rx="1" />
    <rect x="13" y="8" width="3" height="9" rx="1" />
    <path d="M7.5 8.5 12 5l4 2.5 3.5-3" />
  </Svg>
);

export const IconUsers = (p: P) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 19.5c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
    <path d="M16 5.2a3.2 3.2 0 0 1 0 5.6M17.5 14.8c2 .7 3.3 2.4 3.3 4.7" />
  </Svg>
);

export const IconSchool = (p: P) => (
  <Svg {...p}>
    <path d="M4 20.5h16" />
    <path d="M5.5 20.5V9l6.5-4 6.5 4v11.5" />
    <path d="M10 20.5v-4.5h4v4.5" />
    <path d="M9.5 11h1.5M13 11h1.5" />
  </Svg>
);

export const IconMap = (p: P) => (
  <Svg {...p}>
    <path d="m9 4.5 6 2.2 5-2.2v13.3l-5 2.2-6-2.2-5 2.2V6.7Z" />
    <path d="M9 4.5v13.3M15 6.7V20" />
  </Svg>
);

export const IconFamily = (p: P) => (
  <Svg {...p}>
    <circle cx="8" cy="7.5" r="2.7" />
    <circle cx="16.5" cy="8.5" r="2.2" />
    <path d="M3.5 19.5c0-2.8 2-4.7 4.5-4.7s4.5 1.9 4.5 4.7" />
    <path d="M14 14.9c.7-.4 1.5-.6 2.5-.6 2.2 0 3.9 1.6 3.9 4.1" />
  </Svg>
);

export const IconBriefcase = (p: P) => (
  <Svg {...p}>
    <rect x="3.5" y="7.5" width="17" height="12" rx="2.5" />
    <path d="M9 7.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5" />
    <path d="M3.5 12.5h17" />
  </Svg>
);

/* ——— ui ——— */
export const IconLogout = (p: P) => (
  <Svg {...p}>
    <path d="M14 4.5H7.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H14" />
    <path d="M17 8.5 20.5 12 17 15.5M20 12H10" />
  </Svg>
);

export const IconMenu = (p: P) => (
  <Svg {...p}>
    <path d="M4 6.5h16M4 12h16M4 17.5h16" />
  </Svg>
);

export const IconX = (p: P) => (
  <Svg {...p}>
    <path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />
  </Svg>
);

export const IconChevronDown = (p: P) => (
  <Svg {...p}>
    <path d="m6.5 9.5 5.5 5.5 5.5-5.5" />
  </Svg>
);

export const IconChevronLeft = (p: P) => (
  <Svg {...p}>
    <path d="m14.5 6.5-5.5 5.5 5.5 5.5" />
  </Svg>
);

export const IconArrowLeft = (p: P) => (
  <Svg {...p}>
    <path d="M19 12H5M11.5 5.5 5 12l6.5 6.5" />
  </Svg>
);

export const IconArrowUp = (p: P) => (
  <Svg {...p}>
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  </Svg>
);

export const IconArrowDown = (p: P) => (
  <Svg {...p}>
    <path d="M12 5v14M5.5 12.5 12 19l6.5-6.5" />
  </Svg>
);

export const IconSearch = (p: P) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4 4" />
  </Svg>
);

export const IconPlus = (p: P) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconCheck = (p: P) => (
  <Svg {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
);

export const IconCheckCircle = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="m8.5 12.2 2.4 2.4 4.6-4.8" />
  </Svg>
);

export const IconInfo = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5M12 8h.01" />
  </Svg>
);

export const IconTarget = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="1" />
  </Svg>
);

export const IconTrend = (p: P) => (
  <Svg {...p}>
    <path d="m4 16.5 5-5 3.5 3.5L20 7.5" />
    <path d="M15.5 7.5H20V12" />
  </Svg>
);

export const IconClock = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Svg>
);

export const IconInbox = (p: P) => (
  <Svg {...p}>
    <path d="M4 13.5 6.2 5.4A2 2 0 0 1 8.1 4h7.8a2 2 0 0 1 1.9 1.4L20 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" />
    <path d="M4 13.5h4l1.2 2.2h5.6L16 13.5h4" />
  </Svg>
);

export const IconSend = (p: P) => (
  <Svg {...p}>
    <path d="M20 4 3.8 10.4c-.7.3-.7 1.3 0 1.6L9.5 14l1.7 5.4c.2.7 1.1.8 1.6.3L20.6 15c.5-.5.5-1.3-.1-1.7Z" />
    <path d="M20 4 11.2 14" />
  </Svg>
);

export const IconRefresh = (p: P) => (
  <Svg {...p}>
    <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
    <path d="M19.5 4.5V9H15" />
  </Svg>
);

export const IconFilter = (p: P) => (
  <Svg {...p}>
    <path d="M4.5 6h15M7.5 12h9M10.5 18h3" />
  </Svg>
);

export const IconShield = (p: P) => (
  <Svg {...p}>
    <path d="M12 3.5 5 6v5.5c0 4 2.9 7.5 7 9 4.1-1.5 7-5 7-9V6Z" />
    <path d="m9 12 2 2 4-4.2" />
  </Svg>
);

export const IconLayers = (p: P) => (
  <Svg {...p}>
    <path d="m12 3.5 8.5 4.3-8.5 4.3-8.5-4.3Z" />
    <path d="m4 12.3 8 4 8-4M4 16.3l8 4 8-4" />
  </Svg>
);

export const IconGraduation = (p: P) => (
  <Svg {...p}>
    <path d="M12 4.5 3 9l9 4.5L21 9Z" />
    <path d="M7 11.5V16c0 1.4 2.2 2.8 5 2.8s5-1.4 5-2.8v-4.5" />
    <path d="M21 9v5" />
  </Svg>
);

export const IconLock = (p: P) => (
  <Svg {...p}>
    <rect x="5" y="10.5" width="14" height="10" rx="2.5" />
    <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    <path d="M12 14.5v2" />
  </Svg>
);

export const IconUser = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="8.5" r="3.5" />
    <path d="M5 20c0-3.4 3.1-5.7 7-5.7s7 2.3 7 5.7" />
  </Svg>
);

export const IconChat = (p: P) => (
  <Svg {...p}>
    <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 3.5V16H6.5A2.5 2.5 0 0 1 4 13.5Z" />
    <path d="M8.5 9h7M8.5 12h4" />
  </Svg>
);

export const IconCompass = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="m14.8 9.2-1.6 4-4 1.6 1.6-4Z" />
  </Svg>
);
