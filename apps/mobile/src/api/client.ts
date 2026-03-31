import axios from "axios";
import { Platform } from "react-native";

import { decodeEscapedText } from "../utils/text";

function trimSlash(s: string): string {
  const v = String(s || "");
  return v.replace(/\/$/, "");
}

function resolveBase(raw: string): string {
  const t = trimSlash(raw);

  const os = Platform.OS;
  if (os !== "web") {
    return t;
  }
  if (typeof window === "undefined") {
    return t;
  }

  let isDev = false;
  if (typeof __DEV__ !== "undefined" && __DEV__) {
    isDev = true;
  }
  if (!isDev) {
    return t;
  }

  try {
    const u = new URL(t);
    const h = String(window.location.hostname || "").trim();
    if (h === "") {
      return t;
    }
    u.hostname = h;
    return trimSlash(u.toString());
  } catch {
    return t;
  }
}

const cfgUrl =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  (typeof __DEV__ !== "undefined" && __DEV__ ? "http://127.0.0.1:8000" : "http://47.84.99.189:8000");
export const apiBaseURL = resolveBase(cfgUrl);

function setPort(raw: string, p: string): string {
  const t = trimSlash(raw);
  const m = t.match(/^(https?:\/\/[^/:]+)(?::\d+)?(\/.*)?$/i);
  if (!m) {
    return t;
  }
  const host = m[1];
  const path = m[2] || "";
  return `${host}:${p}${path}`;
}

export const asrBaseURL = resolveBase(
  process.env.EXPO_PUBLIC_ASR_BASE_URL || setPort(apiBaseURL, "8013")
);

export const httpClient = axios.create({
  baseURL: apiBaseURL,
  timeout: 20000,
});

function norm(v: any): any {
  if (typeof v === "string") {
    return decodeEscapedText(v);
  }
  if (Array.isArray(v)) {
    const arr: any[] = [];
    for (let i = 0; i < v.length; i++) {
      arr.push(norm(v[i]));
    }
    return arr;
  }
  if (v && typeof v === "object") {
    const out: Record<string, any> = {};
    const keys = Object.keys(v);
    for (let j = 0; j < keys.length; j++) {
      const k = keys[j];
      out[k] = norm(v[k]);
    }
    return out;
  }
  return v;
}

httpClient.interceptors.response.use((rsp) => {
  rsp.data = norm(rsp.data);
  return rsp;
});

const mockEnv = process.env.EXPO_PUBLIC_API_MOCK || "false";
export const isMockMode = mockEnv === "true";

export function getWsBaseUrl() {
  let ws = apiBaseURL;
  if (ws.startsWith("https://")) {
    ws = ws.replace("https://", "wss://");
  } else {
    ws = ws.replace("http://", "ws://");
  }
  return ws;
}
