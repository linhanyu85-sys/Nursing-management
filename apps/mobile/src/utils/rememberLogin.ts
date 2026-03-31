import * as FileSystem from "expo-file-system";

type RememberedLogin = {
  username: string;
  password: string;
  remember: boolean;
};

const EMPTY: RememberedLogin = {
  username: "",
  password: "",
  remember: false,
};

const FILE_PATH = `${FileSystem.documentDirectory || ""}remember_login.json`;

export async function loadRememberedLogin(): Promise<RememberedLogin> {
  try {
    if (!FileSystem.documentDirectory) {
      return EMPTY;
    }
    const info = await FileSystem.getInfoAsync(FILE_PATH);
    if (!info.exists) {
      return EMPTY;
    }
    const raw = await FileSystem.readAsStringAsync(FILE_PATH, { encoding: FileSystem.EncodingType.UTF8 });
    const parsed = JSON.parse(raw || "{}");
    const username = typeof parsed.username === "string" ? parsed.username : "";
    const password = typeof parsed.password === "string" ? parsed.password : "";
    const remember = Boolean(parsed.remember && username && password);
    return { username, password, remember };
  } catch {
    return EMPTY;
  }
}

export async function saveRememberedLogin(username: string, password: string): Promise<void> {
  try {
    if (!FileSystem.documentDirectory) {
      return;
    }
    const payload: RememberedLogin = {
      username: username.trim(),
      password,
      remember: true,
    };
    await FileSystem.writeAsStringAsync(FILE_PATH, JSON.stringify(payload), {
      encoding: FileSystem.EncodingType.UTF8,
    });
  } catch {
    // ignore
  }
}

export async function clearRememberedLogin(): Promise<void> {
  try {
    if (!FileSystem.documentDirectory) {
      return;
    }
    const info = await FileSystem.getInfoAsync(FILE_PATH);
    if (info.exists) {
      await FileSystem.deleteAsync(FILE_PATH, { idempotent: true });
    }
  } catch {
    // ignore
  }
}

