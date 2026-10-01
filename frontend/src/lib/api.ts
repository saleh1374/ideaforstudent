export type HomeData = {
  progress_pct: number;
  mastery_pct: number;
  gap: number;
  errors_total: number;
  errors_resolved: number;
  resolved_pct: number;
  next_exam: { id: number; title: string } | null;
  status_counts: Record<string, number>;
};

export type TopicNode = {
  id: number;
  title: string;
  period: number | null;
  mastery: number | null;
  effective_mastery: number | null;
  status: string;
};

export type BookNode = {
  id: number;
  title: string;
  subject: string;
  chapters: { id: number; title: string; topics: TopicNode[] }[];
};

export type ExamSummary = {
  id: number;
  title: string;
  type: string;
  subject: string;
  grade: string;
  opens_at: string | null;
  closes_at: string | null;
  item_count: number;
};

export type ExamItemOut = {
  exam_item_id: number;
  order: number;
  body: string;
  options: Record<string, string>;
  points: number;
};

export type ErrorOut = {
  id: number;
  topic_id: number;
  cause: string;
  status: string;
  item: { body: string; options: Record<string, string>; correct: string };
  created_at: string;
};

const TOKEN_KEY = "daneshyar_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string | null) {
  if (typeof window === "undefined") return;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string>) },
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    setToken(null);
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function login(username: string, password: string) {
  const data = await api<{ token: string; user: { id: number; full_name: string; role: string } }>(
    "/auth/login",
    { method: "POST", json: { username, password } }
  );
  setToken(data.token);
  // cached for instant, role-aware navigation (cleared on logout)
  try {
    localStorage.setItem("daneshyar_role", data.user.role);
    localStorage.setItem("daneshyar_name", data.user.full_name);
  } catch {
    /* storage unavailable */
  }
  return data;
}
