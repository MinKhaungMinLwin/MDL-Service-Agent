import { NextResponse } from "next/server";
import { normalizeBacklogItem } from "@/lib/backlog-utils";
import { readBacklogItems, readJsonFile, writeJsonFile, newId } from "@/lib/storage";
import type { Locale } from "@/lib/i18n";
import type { BacklogItem } from "@/lib/types";

export async function GET(request: Request) {
  const locale = (new URL(request.url).searchParams.get("locale") ?? "ko") as Locale;
  const items = await readBacklogItems(locale === "en" ? "en" : "ko");
  return NextResponse.json(items);
}

export async function POST(request: Request) {
  const body = (await request.json()) as Omit<BacklogItem, "id">;
  const items = await readJsonFile<BacklogItem[]>("backlog.json", []);
  const item: BacklogItem = normalizeBacklogItem({ ...body, id: newId("bl") });
  items.push(item);
  await writeJsonFile("backlog.json", items);
  return NextResponse.json(item, { status: 201 });
}

export async function PUT(request: Request) {
  const body = (await request.json()) as BacklogItem;
  const items = await readJsonFile<BacklogItem[]>("backlog.json", []);
  const idx = items.findIndex((i) => i.id === body.id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });
  items[idx] = normalizeBacklogItem(body);
  await writeJsonFile("backlog.json", items);
  return NextResponse.json(items[idx]);
}

export async function DELETE(request: Request) {
  const { id } = (await request.json()) as { id: string };
  const items = await readJsonFile<BacklogItem[]>("backlog.json", []);
  const filtered = items.filter((i) => i.id !== id);
  if (filtered.length === items.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await writeJsonFile("backlog.json", filtered);
  return NextResponse.json({ ok: true });
}
