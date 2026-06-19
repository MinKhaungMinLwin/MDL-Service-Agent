import { NextResponse } from "next/server";
import { normalizeAgent, readAgents } from "@/lib/agent-utils";
import { newId, writeJsonFile } from "@/lib/storage";
import type { Agent } from "@/lib/types";

export async function GET() {
  const items = await readAgents();
  return NextResponse.json(items);
}

export async function POST(request: Request) {
  const body = normalizeAgent(await request.json());
  if (!body.name) {
    return NextResponse.json({ error: "Name is required" }, { status: 400 });
  }

  const items = await readAgents();
  const today = new Date().toISOString().slice(0, 10);
  const item: Agent = {
    ...body,
    id: newId("agt"),
    createdAt: today,
    updatedAt: today,
  };
  items.push(item);
  await writeJsonFile("agents.json", items);
  return NextResponse.json(item, { status: 201 });
}

export async function PUT(request: Request) {
  const body = normalizeAgent(await request.json());
  if (!body.id || !body.name) {
    return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
  }

  const items = await readAgents();
  const idx = items.findIndex((item) => item.id === body.id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const updated: Agent = {
    ...items[idx],
    name: body.name,
    description: body.description,
    status: body.status,
    logic: body.logic,
    flow: body.flow,
    updatedAt: new Date().toISOString().slice(0, 10),
  };
  items[idx] = updated;
  await writeJsonFile("agents.json", items);
  return NextResponse.json(updated);
}

export async function DELETE(request: Request) {
  const { id } = (await request.json()) as { id: string };
  const items = await readAgents();
  const filtered = items.filter((item) => item.id !== id);
  if (filtered.length === items.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  await writeJsonFile("agents.json", filtered);
  return NextResponse.json({ ok: true });
}
