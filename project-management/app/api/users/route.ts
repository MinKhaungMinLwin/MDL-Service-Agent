import { NextResponse } from "next/server";
import { readJsonFile, writeJsonFile, newId } from "@/lib/storage";
import { normalizeUserRecord, toPublicUser } from "@/lib/user-utils";
import type { UserRecord } from "@/lib/types";

function findDuplicateEmail(items: UserRecord[], email: string, excludeId?: string) {
  return items.some(
    (item) => item.email === email && (!excludeId || item.id !== excludeId),
  );
}

export async function GET() {
  const items = await readJsonFile<UserRecord[]>("users.json", []);
  return NextResponse.json(items.map(toPublicUser));
}

export async function POST(request: Request) {
  const body = normalizeUserRecord(await request.json());
  if (!body.email || !body.name || !body.password) {
    return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
  }

  const items = await readJsonFile<UserRecord[]>("users.json", []);
  if (findDuplicateEmail(items, body.email)) {
    return NextResponse.json({ error: "Email already exists" }, { status: 409 });
  }

  const item: UserRecord = {
    id: newId("usr"),
    email: body.email,
    name: body.name,
    password: body.password,
    createdAt: new Date().toISOString().slice(0, 10),
  };
  items.push(item);
  await writeJsonFile("users.json", items);
  return NextResponse.json(toPublicUser(item), { status: 201 });
}

export async function PUT(request: Request) {
  const body = normalizeUserRecord(await request.json());
  if (!body.id || !body.email || !body.name) {
    return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
  }

  const items = await readJsonFile<UserRecord[]>("users.json", []);
  const idx = items.findIndex((item) => item.id === body.id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });
  if (findDuplicateEmail(items, body.email, body.id)) {
    return NextResponse.json({ error: "Email already exists" }, { status: 409 });
  }

  const updated: UserRecord = {
    ...items[idx],
    email: body.email,
    name: body.name,
    password: body.password || items[idx].password,
  };
  items[idx] = updated;
  await writeJsonFile("users.json", items);
  return NextResponse.json(toPublicUser(updated));
}

export async function DELETE(request: Request) {
  const { id } = (await request.json()) as { id: string };
  const items = await readJsonFile<UserRecord[]>("users.json", []);
  const filtered = items.filter((item) => item.id !== id);
  if (filtered.length === items.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await writeJsonFile("users.json", filtered);
  return NextResponse.json({ ok: true });
}
