import { NextResponse } from "next/server";
import { readMarkdown } from "@/lib/storage";
import type { Locale } from "@/lib/i18n";

type Params = { params: Promise<{ locale: string; path: string[] }> };

export async function GET(_request: Request, { params }: Params) {
  const { locale, path } = await params;
  if (locale !== "ko" && locale !== "en") {
    return NextResponse.json({ error: "Invalid locale" }, { status: 400 });
  }
  const contentPath = path.join("/");
  try {
    const markdown = await readMarkdown(locale as Locale, contentPath);
    return new NextResponse(markdown, {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
}
