import { NextResponse } from "next/server";
import { readJsonFile, writeJsonFile, newId } from "@/lib/storage";
import type { Issue } from "@/lib/types";

export async function GET() {
  const items = await readJsonFile<Issue[]>("issues.json", []);
  return NextResponse.json(items);
}

export async function POST(request: Request) {
  const body = (await request.json()) as Omit<Issue, "id" | "createdAt">;
  const items = await readJsonFile<Issue[]>("issues.json", []);
  const item: Issue = {
    ...body,
    id: newId("is"),
    createdAt: new Date().toISOString().slice(0, 10),
  };
  items.push(item);
  await writeJsonFile("issues.json", items);
  return NextResponse.json(item, { status: 201 });
}

export async function PUT(request: Request) {
  const body = (await request.json()) as Issue;
  const items = await readJsonFile<Issue[]>("issues.json", []);
  const idx = items.findIndex((i) => i.id === body.id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });
  items[idx] = body;
  await writeJsonFile("issues.json", items);
  return NextResponse.json(body);
}

export async function DELETE(request: Request) {
  const { id } = (await request.json()) as { id: string };
  const items = await readJsonFile<Issue[]>("issues.json", []);
  const filtered = items.filter((i) => i.id !== id);
  if (filtered.length === items.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await writeJsonFile("issues.json", filtered);
  return NextResponse.json({ ok: true });
}
