import { readMarkdown } from "@/lib/storage";
import type { Locale } from "@/lib/i18n";

export async function loadContentBoth(
  contentPath: string,
): Promise<Partial<Record<Locale, string>>> {
  const [ko, en] = await Promise.all([
    readMarkdown("ko", contentPath).catch(() => ""),
    readMarkdown("en", contentPath).catch(() => ""),
  ]);
  return { ko, en };
}
