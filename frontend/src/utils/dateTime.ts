const CHINA_TIME_ZONE = "Asia/Shanghai";
const CHINA_TIME_OFFSET = "+08:00";

type DateTimeInput = string | number | Date | null | undefined;

function normalizeDateInput(value: Exclude<DateTimeInput, null | undefined>) {
  if (value instanceof Date || typeof value === "number") {
    return value;
  }

  const text = value.trim();
  if (!text) {
    return text;
  }

  const hasTimeZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(text);
  if (/^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(text) && !hasTimeZone) {
    return `${text.replace(" ", "T")}${CHINA_TIME_OFFSET}`;
  }

  return text;
}

export function formatChinaDateTime(value: DateTimeInput, locale = "zh-CN", fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  const normalized = normalizeDateInput(value);
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString(locale, {
    timeZone: CHINA_TIME_ZONE,
    hour12: false,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
