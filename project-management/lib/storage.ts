import fs from "fs/promises";
import path from "path";
import type { Locale } from "@/lib/i18n";
import { normalizeBacklogItem } from "@/lib/backlog-utils";
import { normalizeWorkItem } from "@/lib/work-utils";
import type { BacklogItem, WorkItem } from "@/lib/types";

const DATA_DIR = path.join(process.cwd(), "data");
const CONTENT_DIR = path.join(process.cwd(), "content");

export async function readJsonFile<T>(filename: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(path.join(DATA_DIR, filename), "utf8");
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export async function writeJsonFile<T>(filename: string, data: T): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(path.join(DATA_DIR, filename), JSON.stringify(data, null, 2), "utf8");
}

/** @deprecated Use readMarkdown instead */
export async function readContentHtml(relativePath: string): Promise<string> {
  return fs.readFile(path.join(CONTENT_DIR, relativePath), "utf8");
}

export async function readMarkdown(locale: Locale, contentPath: string): Promise<string> {
  const filePath = path.join(CONTENT_DIR, locale, `${contentPath}.md`);
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    if (locale !== "ko") {
      return readMarkdown("ko", contentPath);
    }
    throw new Error(`Content not found: ${locale}/${contentPath}.md`);
  }
}

export function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}`;
}

export async function readWorkItems(): Promise<WorkItem[]> {
  const items = await readJsonFile<WorkItem[]>("work.json", []);
  return items.map((item) => normalizeWorkItem(item));
}

type BacklogText = Pick<BacklogItem, "id" | "l1" | "l2" | "task" | "deliverable">;

export async function readBacklogItems(locale: Locale): Promise<BacklogItem[]> {
  const ko = await readJsonFile<BacklogItem[]>("backlog.json", []);
  const normalized = ko.map((item) => normalizeBacklogItem(item));
  if (locale === "ko") return normalized;

  const en = await readJsonFile<BacklogText[]>("backlog.en.json", []);
  const enMap = new Map(en.map((item) => [item.id, item]));

  return normalized.map((item) => {
    const translated = enMap.get(item.id);
    if (!translated) return item;
    return {
      ...item,
      l1: translated.l1,
      l2: translated.l2,
      task: translated.task,
      deliverable: translated.deliverable,
    };
  });
}
