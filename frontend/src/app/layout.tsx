import type { Metadata } from "next";
import { Vazirmatn } from "next/font/google";
import "./globals.css";

const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  variable: "--font-vazirmatn",
  display: "swap",
  weight: "variable",
});

export const metadata: Metadata = {
  title: "دانشیار — پلتفرم آموزشی تحلیلی",
  description: "پنل دانش‌آموز، معلم، مدیر و والدین با مدل یادگیری SLM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body className={`${vazirmatn.variable} font-sans`}>{children}</body>
    </html>
  );
}
