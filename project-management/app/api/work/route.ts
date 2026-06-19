import { NextResponse } from "next/server";
import { normalizeWorkItem } from "@/lib/work-utils";
import { readJsonFile, writeJsonFile, newId } from "@/lib/storage";
import type { WorkItem } from "@/lib/types";

export async function GET() {
  const items = await readJsonFile<WorkItem[]>("work.json", []);
  return NextResponse.json(items.map((item) => normalizeWorkItem(item)));
}

export async function POST(request: Request) {
  const body = (await request.json()) as Omit<WorkItem, "id">;
  const items = await readJsonFile<WorkItem[]>("work.json", []);
  const item = normalizeWorkItem({ ...body, id: newId("wk") });
  items.push(item);
  await writeJsonFile("work.json", items);
  return NextResponse.json(item, { status: 201 });
}

export async function PUT(request: Request) {
  const body = (await request.json()) as WorkItem;
  const items = await readJsonFile<WorkItem[]>("work.json", []);
  const idx = items.findIndex((i) => i.id === body.id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });
  items[idx] = normalizeWorkItem(body);
  await writeJsonFile("work.json", items);
  return NextResponse.json(items[idx]);
}

export async function DELETE(request: Request) {
  const { id } = (await request.json()) as { id: string };
  const items = await readJsonFile<WorkItem[]>("work.json", []);
  const filtered = items.filter((i) => i.id !== id);
  if (filtered.length === items.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await writeJsonFile("work.json", filtered);
  return NextResponse.json({ ok: true });
}
