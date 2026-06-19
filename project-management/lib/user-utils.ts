import type { User, UserRecord } from "@/lib/types";

export function normalizeUserRecord(raw: Partial<UserRecord>): UserRecord {
  return {
    id: raw.id ?? "",
    email: raw.email?.trim().toLowerCase() ?? "",
    name: raw.name?.trim() ?? "",
    password: raw.password ?? "",
    createdAt: raw.createdAt ?? "",
  };
}

export function toPublicUser(record: UserRecord): User {
  return {
    id: record.id,
    email: record.email,
    name: record.name,
    createdAt: record.createdAt,
  };
}
