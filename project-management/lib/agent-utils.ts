import type { Agent } from "@/lib/types";

export function normalizeAgent(raw: Partial<Agent>): Agent {
  const today = new Date().toISOString().slice(0, 10);
  return {
    id: raw.id ?? "",
    name: raw.name?.trim() ?? "",
    description: raw.description?.trim() ?? "",
    status: raw.status ?? "개발중",
    logic: raw.logic ?? "",
    flow: raw.flow ?? "",
    createdAt: raw.createdAt ?? today,
    updatedAt: raw.updatedAt ?? today,
  };
}

export async function readAgents(): Promise<Agent[]> {
  const { readJsonFile } = await import("@/lib/storage");
  const items = await readJsonFile<Agent[]>("agents.json", []);
  return items.map((item) => normalizeAgent(item));
}
