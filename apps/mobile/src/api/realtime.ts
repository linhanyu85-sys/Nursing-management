import { getWsBaseUrl } from "./client";

type MsgCb<T> = (d: T) => void;
type ErrCb = (msg: string) => void;

export function subscribePatientContext(
  pid: string,
  onMsg: MsgCb<any>,
  onErr?: ErrCb
) {
  const base = getWsBaseUrl();
  const url = `${base}/ws/patient-context/${pid}`;
  const sock = new WebSocket(url);

  sock.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      onMsg(d);
    } catch {
      if (onErr) onErr("实时数据解析失败");
    }
  };

  sock.onerror = () => {
    if (onErr) onErr("患者实时流连接失败");
  };

  return () => {
    try {
      sock.close();
    } catch {
    }
  };
}

export function subscribeWardBeds(
  deptId: string,
  onMsg: MsgCb<any>,
  onErr?: ErrCb
) {
  const base = getWsBaseUrl();
  const url = `${base}/ws/ward-beds/${deptId}`;
  const sock = new WebSocket(url);

  sock.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      onMsg(d);
    } catch {
      if (onErr) onErr("病区实时数据解析失败");
    }
  };

  sock.onerror = () => {
    if (onErr) onErr("病区实时流连接失败");
  };

  return () => {
    try {
      sock.close();
    } catch {
    }
  };
}
