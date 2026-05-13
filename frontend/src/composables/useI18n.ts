import { ref } from "vue";
import { DEFAULT_LOCALE, messages, SUPPORTED_LOCALES, type LocaleCode } from "../i18n/messages";

const STORAGE_KEY = "rga.locale";

function readInitialLocale(): LocaleCode {
  if (typeof window === "undefined") {
    return DEFAULT_LOCALE;
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored && SUPPORTED_LOCALES.some((item) => item.code === stored)) {
    return stored as LocaleCode;
  }
  return DEFAULT_LOCALE;
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, key) => {
    const value = params[key];
    return value === undefined || value === null ? match : String(value);
  });
}

const locale = ref<LocaleCode>(readInitialLocale());

function persistLocale(value: LocaleCode) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, value);
  }
}

persistLocale(locale.value);

export function useI18n() {

  function t(key: string, params?: Record<string, string | number>): string {
    const currentMessages = messages[locale.value] ?? messages[DEFAULT_LOCALE];
    const template = currentMessages[key] ?? messages[DEFAULT_LOCALE][key] ?? key;
    return interpolate(template, params);
  }

  function setLocale(next: LocaleCode) {
    locale.value = next;
    persistLocale(next);
  }

  return {
    locale,
    localeOptions: SUPPORTED_LOCALES,
    t,
    setLocale,
  };
}
