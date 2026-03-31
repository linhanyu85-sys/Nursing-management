import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";
import * as Speech from "expo-speech";

import { api } from "../api/endpoints";

type SpeakMode = "api_audio" | "device_tts";

export type SpeakResult = {
  mode: SpeakMode;
  detail: string;
};

const MOCK_AUDIO_BASE64 = "TU9DS19BVURJT19EQVRB";

let currentSound: Audio.Sound | null = null;
let currentFileUri: string | null = null;

function parseDataUri(input: string): { base64: string; mime?: string } {
  const raw = (input || "").trim();
  const matched = raw.match(/^data:([^;]+);base64,(.+)$/i);
  if (!matched) {
    return { base64: raw };
  }
  return {
    mime: matched[1],
    base64: matched[2],
  };
}

function extFromMime(mime?: string): string {
  if (!mime) {
    return "wav";
  }
  const normalized = mime.toLowerCase();
  if (normalized.includes("mpeg") || normalized.includes("mp3")) {
    return "mp3";
  }
  if (normalized.includes("m4a") || normalized.includes("mp4") || normalized.includes("aac")) {
    return "m4a";
  }
  return "wav";
}

async function clearCurrentPlayback(): Promise<void> {
  try {
    Speech.stop();
  } catch {
    // ignore
  }

  try {
    if (currentSound) {
      await currentSound.stopAsync().catch(() => null);
      await currentSound.unloadAsync().catch(() => null);
      currentSound = null;
    }
  } catch {
    // ignore
  }

  try {
    if (currentFileUri) {
      await FileSystem.deleteAsync(currentFileUri, { idempotent: true });
      currentFileUri = null;
    }
  } catch {
    // ignore
  }
}

async function playFromBase64(base64: string, mimeHint?: string): Promise<boolean> {
  if (!base64) {
    return false;
  }
  const cacheRoot = FileSystem.cacheDirectory || FileSystem.documentDirectory;
  if (!cacheRoot) {
    return false;
  }

  const candidates = Array.from(
    new Set(
      [mimeHint, "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac"].filter(Boolean)
    )
  ) as string[];

  await Audio.setAudioModeAsync({
    allowsRecordingIOS: false,
    playsInSilentModeIOS: true,
    shouldDuckAndroid: true,
    staysActiveInBackground: false,
  });

  for (const mime of candidates) {
    const ext = extFromMime(mime);
    const fileUri = `${cacheRoot}tts_${Date.now()}_${Math.random().toString(36).slice(2)}.${ext}`;
    try {
      await FileSystem.writeAsStringAsync(fileUri, base64, { encoding: FileSystem.EncodingType.Base64 });
      const { sound } = await Audio.Sound.createAsync({ uri: fileUri }, { shouldPlay: true });
      currentSound = sound;
      currentFileUri = fileUri;
      sound.setOnPlaybackStatusUpdate((status) => {
        if (!status.isLoaded) {
          return;
        }
        if (status.didJustFinish) {
          void clearCurrentPlayback();
        }
      });
      return true;
    } catch {
      await FileSystem.deleteAsync(fileUri, { idempotent: true }).catch(() => null);
    }
  }
  return false;
}

function speakWithDevice(text: string): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) {
        return;
      }
      done = true;
      resolve();
    };
    Speech.stop();
    Speech.speak(text, {
      language: "zh-CN",
      rate: 0.96,
      pitch: 1.0,
      onStart: () => {
        setTimeout(finish, 300);
      },
      onDone: finish,
      onStopped: finish,
      onError: finish,
    });
    setTimeout(finish, 1200);
  });
}

export async function speakSummaryText(text: string): Promise<SpeakResult> {
  const plain = (text || "").trim();
  if (!plain) {
    throw new Error("empty_text");
  }

  await clearCurrentPlayback();

  try {
    const tts = await api.ttsSpeak(plain);
    const provider = String(tts?.provider || "");
    const rawAudio = String(tts?.audio_base64 || "").trim();
    const shouldTryApiAudio =
      !!rawAudio && rawAudio !== MOCK_AUDIO_BASE64 && provider !== "mock" && provider !== "fallback";

    if (shouldTryApiAudio) {
      const parsed = parseDataUri(rawAudio);
      const ok = await playFromBase64(parsed.base64, parsed.mime);
      if (ok) {
        return {
          mode: "api_audio",
          detail: "正在播放语音播报（TTS服务音频）。",
        };
      }
    }
  } catch {
    // fallback to device speech
  }

  await speakWithDevice(plain);
  return {
    mode: "device_tts",
    detail: "TTS服务音频不可播，已切换手机本地语音播报。",
  };
}

