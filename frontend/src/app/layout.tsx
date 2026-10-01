import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "دانشیار — پلتفرم آموزشی تحلیلی",
  description: "پنل دانش‌آموز، معلم، مدیر و والدین با مدل یادگیری SLM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <head>
        <link
          href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
