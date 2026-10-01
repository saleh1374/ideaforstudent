"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";

const DEMO_USERS = [
  { u: "student1", label: "دانش‌آموز" },
  { u: "teacher1", label: "معلم" },
  { u: "schooladmin", label: "مدیر مدرسه" },
  { u: "districtadmin", label: "مدیر ناحیه" },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("student1");
  const [password, setPassword] = useState("pass123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(username, password);
      if (data.user.role === "student") router.push("/student");
      else if (data.user.role === "teacher") router.push("/teacher");
      else router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ورود");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="card w-full max-w-md space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold text-primary-700">دانشیار</h1>
          <p className="text-sm text-slate-500">پلتفرم آموزشی تحلیلی مبتنی بر مدل یادگیری</p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm mb-1 text-slate-600">نام کاربری</label>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm mb-1 text-slate-600">رمز عبور</label>
            <input type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{error}</p>}
          <button className="btn-primary w-full" disabled={loading}>
            {loading ? "در حال ورود…" : "ورود"}
          </button>
        </form>

        <div className="space-y-2">
          <p className="text-xs text-slate-400">کاربرهای نمونه (رمز همه: pass123):</p>
          <div className="flex gap-2">
            {DEMO_USERS.map((d) => (
              <button
                key={d.u}
                className="btn-ghost text-xs flex-1"
                onClick={() => {
                  setUsername(d.u);
                  setPassword("pass123");
                }}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
