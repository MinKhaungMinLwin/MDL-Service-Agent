/** WBS month/week layout (Apr–Oct) aligned with wbs-meta.json */
const WBS_MONTHS: { year: number; month: number; weeks: number }[] = [
  { year: 2026, month: 4, weeks: 5 },
  { year: 2026, month: 5, weeks: 4 },
  { year: 2026, month: 6, weeks: 4 },
  { year: 2026, month: 7, weeks: 5 },
  { year: 2026, month: 8, weeks: 4 },
  { year: 2026, month: 9, weeks: 5 },
  { year: 2026, month: 10, weeks: 4 },
];

export type WeekRange = { start: string; end: string };

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function toIso(year: number, month: number, day: number): string {
  return `${year}-${pad(month)}-${pad(day)}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

export function buildWbsWeekRanges(): WeekRange[] {
  const ranges: WeekRange[] = [];
  for (const { year, month, weeks } of WBS_MONTHS) {
    const dim = daysInMonth(year, month);
    let day = 1;
    for (let w = 0; w < weeks; w++) {
      const remainingWeeks = weeks - w;
      const remainingDays = dim - day + 1;
      const span = Math.max(1, Math.floor(remainingDays / remainingWeeks));
      const endDay = Math.min(day + span - 1, dim);
      ranges.push({
        start: toIso(year, month, day),
        end: toIso(year, month, endDay),
      });
      day = endDay + 1;
    }
  }
  return ranges;
}

export const WBS_WEEK_RANGES = buildWbsWeekRanges();

function parseDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function overlaps(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
  return aStart <= bEnd && bStart <= aEnd;
}

export function timelineToSchedule(timeline: string[]): { scheduleStart: string; scheduleEnd: string } {
  const indices: number[] = [];
  timeline.forEach((cell, i) => {
    if (cell) indices.push(i);
  });
  if (indices.length === 0) return { scheduleStart: "", scheduleEnd: "" };
  const first = indices[0];
  const last = indices[indices.length - 1];
  const ranges = WBS_WEEK_RANGES;
  return {
    scheduleStart: ranges[first]?.start ?? "",
    scheduleEnd: ranges[last]?.end ?? "",
  };
}

export function scheduleToTimeline(
  scheduleStart: string,
  scheduleEnd: string,
  status: string,
): string[] {
  if (!scheduleStart || !scheduleEnd) {
    return Array(WBS_WEEK_RANGES.length).fill("");
  }
  const tlClass =
    status === "완료" ? "tl-done" : status === "진행중" ? "tl-progress" : "tl-planned";
  return WBS_WEEK_RANGES.map((week) =>
    overlaps(scheduleStart, scheduleEnd, week.start, week.end) ? tlClass : "",
  );
}

export function formatScheduleRange(
  start: string,
  end: string,
  locale: "ko" | "en",
): string {
  if (!start && !end) return "";
  if (start && end && start !== end) {
    return locale === "ko" ? `${start} ~ ${end}` : `${start} – ${end}`;
  }
  return start || end;
}
