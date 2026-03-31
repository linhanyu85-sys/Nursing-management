#!/usr/bin/env python3
from __future__ import annotations
import array
import ipaddress
import socket
import base64
import io,json,re,queue,threading,time,subprocess,os,tempfile,wave,shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import requests,serial,serial.tools.list_ports
import tkinter as tk
from tkinter import ttk,messagebox
try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

LOG_PATS=(
    r"^\(\d+\)\s+",
    r"^[A-Z]\s*\(\d+\)\s+",
    r"\bSystemInfo\b",
    r"\bfree\s+sram\b",
    r"\bheap\b",
    r"\bstack\b",
    r"\bwifi\b",
    r"\bboot\b",
    r"\berror:\b",
    r"\bwarn(ing)?\b",
    r"\binfo:\b",
    r"\bApplication:\s*STATE:",
    r"\bxiaoyi_evt:",
    r"\bAFE:\s*AFE\s+Version",
    r"\bAfeWakeWord:\b",
    r"\bAudioService:\b",
    r"^entry\s+0x[0-9a-f]+$",
    r"^esp-rom:",
    r"\bMODEL_LOADER:\b",
    r"\bcrt-bundle:\s*Certificate",
    r"\bSuccessfully\s+load\s+srmodels\b",
)
DEFAULT_USER='linmeili';DEFAULT_WAKE='小医小医';DEFAULT_SLEEP='休眠'
AUTO_CONNECT_DEFAULT=os.getenv('XIAOYI_AUTO_CONNECT','1').strip().lower() not in ('0','false','no','off')
REPROCESS_DEVICE_STT=os.getenv('XIAOYI_REPROCESS_DEVICE_STT','0').strip().lower() in ('1','true','yes','on')
FORCED_DEVICE_HOST=os.getenv('XIAOYI_DEVICE_HOST','').strip()
GATEWAY_PORT=int((os.getenv('XIAOYI_GATEWAY_PORT','8013') or '8013').strip())
STRICT_GATEWAY_PORT=os.getenv('XIAOYI_STRICT_GATEWAY_PORT','1').strip().lower() not in ('0','false','no','off')
PREFERRED_LAN_PREFIX=os.getenv('XIAOYI_PREFERRED_LAN_PREFIX','192.168.').strip() or '192.168.'
PROJECT_BASE=Path(r'D:\Desktop\ai agent 护理精细化部署')
HOST_LOG_DIR=PROJECT_BASE/'logs'
LOCAL_ASR_ROOT=PROJECT_BASE/'services'/'asr-service'/'data'/'local_asr'
LOCAL_ASR_MODEL_SIZE='base'
_LOCAL_ASR_MODEL=None
_LOCAL_ASR_LOCK=threading.Lock()
MOJIBAKE_FIX_MAP={
    "灏忓尰灏忓尰":"小医小医",
    "浼戠湢":"休眠",
    "浣犲ソ灏忓尰":"你好小医",
}
HOST_APP_VERSION='xiaoyi-host-20260322-autoconnect-localmode'
BACKEND_READY_TIMEOUT_SEC=28
BACKEND_RESTART_COOLDOWN_SEC=10

def repair_text(text:str)->str:
    s=(text or "").strip()
    if not s:
        return ""
    # 1) 处理形如 "\\u4f60\\u597d" 的转义文本
    if re.search(r"\\u[0-9a-fA-F]{4}",s):
        try:
            u=bytes(s,'utf-8').decode('unicode_escape')
            if u:
                s=u
        except Exception:
            pass
    # 2) 尝试修复 UTF-8 被当作 latin1 解码造成的乱码（å¼ ææ）
    if (not re.search(r"[\u4e00-\u9fff]",s)) and re.search(r"[ÃÂåæçèéêìíîïðñòóôõöøùúûüýþÿ]",s):
        try:
            fixed=s.encode('latin1',errors='ignore').decode('utf-8',errors='ignore').strip()
            if fixed and re.search(r"[\u4e00-\u9fff]",fixed):
                s=fixed
        except Exception:
            pass
    # 3) 处理 UTF-8 被按 GBK 显示造成的中文乱码（例如“鎴戜笉”“璇风◌”）。
    bad_markers=("鎴","璇","鍖","鏈","妯","锛","銆","闂","鍙","绯","鏂","鎵")
    bad_score=sum(s.count(m) for m in bad_markers)
    if bad_score >= 2:
        candidates=[s]
        try:
            candidates.append(s.encode('gbk',errors='ignore').decode('utf-8',errors='ignore').strip())
        except Exception:
            pass
        try:
            candidates.append(s.encode('latin1',errors='ignore').decode('utf-8',errors='ignore').strip())
        except Exception:
            pass
        def score(t:str)->tuple[int,int]:
            t=t or ""
            bad=sum(t.count(m) for m in bad_markers) + t.count('�')
            cjk=len(re.findall(r"[\u4e00-\u9fff]",t))
            return (bad,-cjk)
        best=min([c for c in candidates if c], key=score, default=s)
        if best:
            s=best
    return s

def visible_name(text:str)->str:
    s=repair_text(text)
    if not s:
        return ""
    # 对外展示统一成“小医”命名，避免旧固件“你好小智”文案干扰
    s=s.replace("你好小智","你好小医")
    s=s.replace("小智","小医")
    return s

def normalize_keyword(text:str, default_value:str)->str:
    s=(text or '').strip()
    if not s:
        return default_value
    s=MOJIBAKE_FIX_MAP.get(s,s)
    s=repair_text(s).strip()
    if not s:
        return default_value
    if "\\u" in s:
        try:
            u=bytes(s,'utf-8').decode('unicode_escape').strip()
            if u:
                s=u
        except Exception:
            pass
    return s or default_value

def decode_serial_line_bytes(raw:bytes)->str:
    b=bytes(raw or b"")
    if not b:
        return ""
    for enc in ("utf-8","gb18030","gbk"):
        try:
            return b.decode(enc,errors="strict")
        except Exception:
            pass
    # 最后兜底，尽量保留信息再交给 repair_text 做二次修复
    try:
        return b.decode("utf-8",errors="ignore")
    except Exception:
        try:
            return b.decode("gb18030",errors="ignore")
        except Exception:
            return ""

@dataclass
class Cfg:
    api:str; dep:str; uid:str; write_back:bool; tts:bool; concise:bool

def is_log_line(s:str)->bool:
    low=s.lower()
    return any(re.search(p,low) for p in LOG_PATS)

def extract_text(line:str)->str|None:
    s=line.strip()
    if not s or is_log_line(s): return None
    if looks_like_base64_noise(s): return None
    low=s.lower()
    if (
        low.startswith('rebooting')
        or 'abort() was called at pc' in low
        or 'guru meditation error' in low
        or 'backtrace:' in low
        or 'core dump' in low
    ):
        return None
    if re.search(r"^[IWE]\s*\(\d+\)\s+",s):
        return None
    if re.search(r"^[A-Z]\s*\(\d+\)\s+[A-Za-z0-9_]+:\s*",s):
        return None
    if "Application: STATE:" in s or "AFE: AFE Version:" in s:
        return None
    # 常见固件启动/底层日志，禁止进入 AI 任务队列
    if (
        re.match(r"^entry\s+0x[0-9a-f]+$",low)
        or low.startswith("esp-rom:")
        or "model_loader:" in low
        or "crt-bundle: certificate" in low
        or "successfully load srmodels" in low
        or re.match(r"^create static modelsi",low)
        or "data loss or overwriting" in low
        or "fetch() to read data" in low
        or re.search(r"\b(avg|peak|buffered|samples|chunks|bytes)=\d+",low)
    ):
        return None
    if s.startswith('{') and s.endswith('}'):
        try:
            o=json.loads(s)
            if isinstance(o,dict):
                for k in ('text','query','content','asr','stt','transcript','recognized_text','utterance','message'):
                    v=o.get(k)
                    if isinstance(v,str) and v.strip(): return repair_text(v)
                p=o.get('payload')
                if isinstance(p,dict):
                    for k in ('text','content','stt','transcript','message'):
                        v=p.get(k)
                        if isinstance(v,str) and v.strip(): return repair_text(v)
        except Exception:
            pass
    for pre in ('ASR:','TEXT:','QUERY:','INPUT:','STT:'):
        if s.upper().startswith(pre):
            t=s[len(pre):].strip()
            if t:return repair_text(t)
    if len(s)<2 or len(s)>240:return None
    if ":" in s and re.match(r"^[A-Za-z_][A-Za-z0-9_ ]{0,32}:\s*",s):
        return None
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]",s):return None
    return repair_text(s)

def parse_xiaozhi_event(line:str)->tuple[str,str]|None:
    s=line.strip()
    if not s:
        return None
    # 兼容上位机/串口日志中可能出现的中括号事件格式
    m=re.search(r"^\[(xiaoyi|xiaozhi)_(wake|stt|tts|state)\]\s*(.+)$",s,re.IGNORECASE)
    if m:
        kind=str(m.group(2) or "").strip().lower()
        payload=repair_text((m.group(3) or "").strip())
        if kind in ("wake","stt","tts","state") and payload:
            return (kind,payload)
    m=re.search(r"XIAOYI_EVT:\s*([A-Za-z_]+)\s*:\s*(.*)$",s,re.IGNORECASE)
    if m:
        k=m.group(1).strip().lower()
        payload=repair_text((m.group(2) or "").strip())
        mp={"wake":"wake","stt":"stt","tts":"tts","state":"state","audio_begin":"audio_begin","audio_chunk":"audio_chunk","audio_end":"audio_end","audio_level":"audio_level"}
        kind=mp.get(k)
        if kind:
            return (kind,payload or "-")
    m=re.search(r"Application:\s*STATE:\s*(.+)$",s,re.IGNORECASE)
    if m and m.group(1).strip():
        return ("state",repair_text(m.group(1).strip()))
    # 典型日志：I (12345) Application: Wake word detected: 你好小智
    m=re.search(r"Wake word detected:\s*(.+)$",s,re.IGNORECASE)
    if m and m.group(1).strip():
        return ("wake",repair_text(m.group(1).strip()))
    # 典型日志：I (...) Application: >> 用户识别文本
    m=re.search(r">>\s*(.+)$",s)
    if m and m.group(1).strip():
        return ("stt",repair_text(m.group(1).strip()))
    # 典型日志：I (...) Application: << TTS句子
    m=re.search(r"<<\s*(.+)$",s)
    if m and m.group(1).strip():
        return ("tts",repair_text(m.group(1).strip()))
    # AFE 唤醒日志：AfeWakeWord: Encode wake word opus ...
    if re.search(r"AfeWakeWord:.*wake word",s,re.IGNORECASE):
        return ("wake","afe_wake")
    # JSON事件：{"type":"stt","text":"..."} / {"type":"tts","state":"sentence_start","text":"..."}
    if s.startswith("{") and s.endswith("}"):
        try:
            o=json.loads(s)
            if isinstance(o,dict):
                t=str(o.get("type") or "").strip().lower()
                if t=="stt":
                    txt=repair_text(str(o.get("text") or "").strip())
                    if txt:return ("stt",txt)
                if t=="tts":
                    txt=repair_text(str(o.get("text") or "").strip())
                    if txt:return ("tts",txt)
                if t=="listen" and str(o.get("state") or "").strip().lower()=="detect":
                    txt=repair_text(str(o.get("text") or "").strip()) or "唤醒词"
                    return ("wake",txt)
        except Exception:
            pass
    return None

def sanitize_base64_text(text:str)->str:
    s=str(text or '').strip()
    if not s:
        return ''
    return re.sub(r'[^A-Za-z0-9+/=]','',s)

def looks_like_base64_noise(text:str)->bool:
    s=(text or '').strip()
    if len(s)<16:
        return False
    if re.search(r'[\u4e00-\u9fff\s]',s):
        return False
    cleaned=sanitize_base64_text(s)
    if len(cleaned)<24 or len(cleaned)!=len(s):
        return False
    return bool(re.fullmatch(r'[A-Za-z0-9+/=]+',cleaned))

def simplify_voice_text(txt:str)->str:
    s=(txt or "").strip().lower()
    if not s:
        return ""
    # 去掉常见标点和空白，提升唤醒/休眠匹配成功率
    s=re.sub(r"[\s,，。.!！?？:：;；'\"`~\-_/\\\[\]\(\)\{\}]+","",s)
    return s

def contains_keyword(text:str,keyword:str)->bool:
    t=simplify_voice_text(text)
    k=simplify_voice_text(keyword)
    if not t or not k:
        return False
    return k in t

def strip_wake_from_text(text:str,wake:str)->str:
    s=(text or "").strip()
    w=(wake or "").strip()
    if not s:
        return ""
    if w and w in s:
        return s.replace(w," ").strip(" ，,。.!！?？")
    # 常见口语：Hi 小医 / 你好小医 / 小医小医，...
    p=r"^(?:hi|hello|嗨|你好)?[\s,，。.!！?？]*?小医(?:[\s,，。.!！?？]*小医)?[\s,，。.!！?？]*"
    return re.sub(p,"",s,flags=re.IGNORECASE).strip(" ，,。.!！?？")

def norm(txt:str)->str:
    t=repair_text((txt or '')).replace('\r\n','\n').replace('\r','\n')
    pats=[(r'^\s*#{1,6}\s*',''),(r'\*\*(.*?)\*\*',r'\1'),(r'\*(.*?)\*',r'\1'),(r'`([^`]*)`',r'\1'),(r'^\s*[-*]\s+','• '),(r'^\s*\|[-:\s|]+\|\s*$','')]
    for p,rp in pats:t=re.sub(p,rp,t,flags=re.MULTILINE)
    def row(m:re.Match[str])->str:
        parts=[c.strip() for c in m.group(1).split('|') if c.strip()]
        return ' / '.join(parts)
    t=re.sub(r'^\s*\|(.+)\|\s*$',row,t,flags=re.MULTILINE)
    t=re.sub(r'\n{3,}','\n\n',t)
    return t.strip()

def brief(summary:str,findings:list[Any],recs:list[Any])->str:
    s=norm(summary)
    lines=[x.strip().strip('•').strip() for x in s.splitlines() if x.strip()]
    parts=[]
    if lines: parts.append(lines[0])
    if findings:
        f=norm(str(findings[0]))
        if f and f not in parts: parts.append(f'发现：{f}')
    if recs:
        r=recs[0]
        rv=(str(r.get('title') or r.get('action') or '').strip() if isinstance(r,dict) else str(r).strip())
        if rv and rv not in parts: parts.append(f'建议：{rv}')
    if not parts: parts=[s[:60] or '已完成分析，请查看详情。']
    out='；'.join(parts)
    out=re.sub(r'\s+',' ',out).strip('；;。,. ')
    if len(out)>90: out=out[:88].rstrip()+'…'
    return f'重点：{out}。'

def get_local_asr_model()->Any:
    global _LOCAL_ASR_MODEL
    if WhisperModel is None:
        raise RuntimeError('faster_whisper_not_installed')
    with _LOCAL_ASR_LOCK:
        if _LOCAL_ASR_MODEL is None:
            LOCAL_ASR_ROOT.mkdir(parents=True,exist_ok=True)
            _LOCAL_ASR_MODEL=WhisperModel(
                LOCAL_ASR_MODEL_SIZE,
                device='cpu',
                compute_type='int8',
                download_root=str(LOCAL_ASR_ROOT),
            )
    return _LOCAL_ASR_MODEL

def transcribe_local_wav_bytes(wav_bytes:bytes,text_hint:str|None=None)->tuple[str,float,str]:
    temp_path=''
    try:
        with tempfile.NamedTemporaryFile(delete=False,suffix='.wav') as tf:
            tf.write(wav_bytes)
            temp_path=tf.name
        model=get_local_asr_model()
        kwargs={
            'task':'transcribe',
            'language':'zh',
            'beam_size':3,
            'vad_filter':True,
            'condition_on_previous_text':False,
        }
        hint=(text_hint or '').strip()
        if hint:
            kwargs['initial_prompt']=hint
        segments,info=model.transcribe(temp_path,**kwargs)
        text=''.join(seg.text for seg in segments).strip()
        confidence=float(getattr(info,'language_probability',0.0) or 0.0)
        if not text:
            segments,info=model.transcribe(
                temp_path,
                task='transcribe',
                language=None,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text=''.join(seg.text for seg in segments).strip()
            confidence=float(getattr(info,'language_probability',0.0) or 0.0)
        return repair_text(text),confidence,f'faster-whisper-{LOCAL_ASR_MODEL_SIZE}'
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError: pass

def bed_no(text:str)->str|None:
    m=re.search(r'(\d{1,3})\s*(床|号床|床位)',text)
    if m:return m.group(1)
    m2=re.search(r'^\s*(\d{1,3})(?=\D|$)',text)
    return m2.group(1) if m2 else None

def bed_candidates(text:str)->list[str]:
    s=(text or '').strip()
    if not s:
        return []
    out:list[str]=[]
    def _add(raw:str)->None:
        try:
            v=int(raw)
        except Exception:
            return
        if v<=0 or v>199:
            return
        n=str(v)
        if n not in out:
            out.append(n)
    for p in (r'(\d{1,3})\s*(床|号床|床位)',r'\bbed\s*(\d{1,3})\b',r'\b(\d{1,3})\s*bed\b'):
        for m in re.finditer(p,s,flags=re.IGNORECASE):
            _add(m.group(1))
    if not out:
        m2=re.search(r'^\s*(\d{1,3})(?=\D|$)',s)
        if m2:
            _add(m2.group(1))
    return out

def resolve_patient(api:str,dep:str,q:str)->tuple[str|None,str|None]:
    beds=bed_candidates(q)
    if not beds:return None,None
    try:
        r=requests.get(f'{api}/api/wards/{dep}/beds',timeout=10);r.raise_for_status();arr=r.json()
        if isinstance(arr,list):
            for b in beds:
                for it in arr:
                    if str(it.get('bed_no') or '')==b:
                        pid=it.get('current_patient_id')
                        if isinstance(pid,str) and pid:return pid,b
    except Exception:
        pass
    return None,beds[0]

class App(tk.Tk):
    def __init__(self)->None:
        super().__init__();self.title(f'小医 AI Agent 上位机 ({HOST_APP_VERSION})');self.geometry('1160x780');self.minsize(1020,680)
        self.base=PROJECT_BASE if PROJECT_BASE.exists() else Path(__file__).resolve().parents[1];self.histf=self.base/'data'/'xiaoyi_host_history.jsonl';self.cfgf=self.base/'data'/'xiaoyi_host_config.json';self.histf.parent.mkdir(parents=True,exist_ok=True)
        # 兼容旧文件名（xiaozhi_*），自动迁移到 xiaoyi_*，避免用户手工处理
        legacy_hist=self.base/'data'/'xiaozhi_host_history.jsonl'
        legacy_cfg=self.base/'data'/'xiaozhi_host_config.json'
        if (not self.histf.exists()) and legacy_hist.exists():
            try: shutil.copy2(legacy_hist,self.histf)
            except Exception: pass
        if (not self.cfgf.exists()) and legacy_cfg.exists():
            try: shutil.copy2(legacy_cfg,self.cfgf)
            except Exception: pass
        c=self._load_cfg();self.q_ui:queue.Queue[tuple[str,Any]]=queue.Queue();self.q_task:queue.Queue[tuple[str,Any]]=queue.Queue();self.stop_w=threading.Event();self.stop_s=threading.Event();self.lock=threading.Lock();self.ser:serial.Serial|None=None;self.s_thread:threading.Thread|None=None;self.hcache:list[dict[str,Any]]=[];self.awake=False
        self.device_state='unknown'
        self.last_voice_event_ts=0.0;self.last_voice_event_kind='';self.last_voice_event_payload='';self.last_xiaozhi_notice_ts=0.0
        self.serial_audio_streaming=False
        self.serial_audio_sr=16000
        self.serial_audio_chunks:list[str]=[]
        self.auto_listen_enabled=True
        self.last_local_mode_cmd_ts=0.0
        self.last_start_listen_ts=0.0
        self.last_mode_log_ts=0.0
        self.detected_wake_model=''
        self.last_model_hint_ts=0.0
        self.supports_xiaoyi_cmd=False
        self.last_proto_warn_ts=0.0
        self.supports_start_listening_cmd:bool|None=None
        self.last_start_probe_ts=0.0
        self.last_cloud_sync_ts=0.0
        self.last_synced_ws_url=''
        self.last_synced_host=''
        self.last_synced_gateway_port=GATEWAY_PORT
        self.last_device_sta_ip=''
        self.last_subnet_mismatch_warn_ts=0.0
        self.last_serial_write_ts=0.0
        self.ws_handshake_fail_count=0
        self.last_ws_handshake_fail_ts=0.0
        self.last_ws_connected_ts=0.0
        self.last_gateway_session_check_ts=0.0
        self.last_gateway_session_seen_ts=0.0
        self.last_device_stt_ts=0.0
        self.last_device_stt_text=''
        self.last_device_tts_ts=0.0
        self.last_backend_start_ts=0.0
        self.backend_bootstrap_lock=threading.Lock()
        self.auto_connect_enabled=AUTO_CONNECT_DEFAULT
        self.auto_connect_retries=0
        self.serial_rx_buffer=bytearray()
        self.var_port=tk.StringVar(value=str(c.get('port','COM5')));self.var_baud=tk.StringVar(value=str(c.get('baud','115200')));self.var_api=tk.StringVar(value=str(c.get('api','http://127.0.0.1:8000')));self.var_dep=tk.StringVar(value=str(c.get('dep','dep-card-01')));self.var_user=tk.StringVar(value=str(c.get('user',DEFAULT_USER)));self.var_wake=tk.StringVar(value=str(c.get('wake',DEFAULT_WAKE)));self.var_sleep=tk.StringVar(value=str(c.get('sleep',DEFAULT_SLEEP)));self.var_write=tk.BooleanVar(value=bool(c.get('write',True)));self.var_raw=tk.BooleanVar(value=bool(c.get('raw',False)));self.var_tts=tk.BooleanVar(value=bool(c.get('tts',True)));self.var_con=tk.BooleanVar(value=bool(c.get('concise',True)));self.var_device_tts=tk.BooleanVar(value=bool(c.get('device_tts',True)));self.var_st=tk.StringVar(value='未连接')
        self._ui();self._ports();self._load_hist();threading.Thread(target=self._worker,daemon=True).start();self.after(100,self._drain);self.protocol('WM_DELETE_WINDOW',self._close)
        if self.auto_connect_enabled:
            self.after(700,self._auto_connect_on_start)
        self._log(f'[host_app] {HOST_APP_VERSION}')

    def _ui(self)->None:
        root=ttk.Frame(self,padding=10);root.pack(fill=tk.BOTH,expand=True)
        top=ttk.LabelFrame(root,text='连接配置',padding=10);top.pack(fill=tk.X)
        ttk.Label(top,text='串口').grid(row=0,column=0,sticky='w');self.cmb=ttk.Combobox(top,textvariable=self.var_port,width=12);self.cmb.grid(row=0,column=1,padx=6);ttk.Button(top,text='刷新串口',command=self._ports).grid(row=0,column=2,padx=6)
        ttk.Label(top,text='波特率').grid(row=0,column=3,sticky='w');ttk.Entry(top,textvariable=self.var_baud,width=10).grid(row=0,column=4,padx=6);self.btn_conn=ttk.Button(top,text='连接串口',command=self._toggle);self.btn_conn.grid(row=0,column=5,padx=6)
        ttk.Checkbutton(top,text='回写到单片机',variable=self.var_write).grid(row=0,column=6,padx=6);ttk.Checkbutton(top,text='显示原始串口行',variable=self.var_raw).grid(row=0,column=7,padx=6);ttk.Label(top,textvariable=self.var_st,foreground='#0f766e').grid(row=0,column=8,sticky='e')
        ttk.Label(top,text='API').grid(row=1,column=0,sticky='w',pady=(8,0));ttk.Entry(top,textvariable=self.var_api,width=34).grid(row=1,column=1,columnspan=2,sticky='we',padx=6,pady=(8,0));ttk.Label(top,text='病区').grid(row=1,column=3,sticky='w',pady=(8,0));ttk.Entry(top,textvariable=self.var_dep,width=12).grid(row=1,column=4,padx=6,pady=(8,0));ttk.Label(top,text='账号').grid(row=1,column=5,sticky='w',pady=(8,0));ttk.Entry(top,textvariable=self.var_user,width=12).grid(row=1,column=6,padx=6,pady=(8,0))
        ttk.Button(top,text='绑定 linmeili',command=self._bind).grid(row=1,column=7,padx=6,pady=(8,0));ttk.Button(top,text='检查网关',command=self._check).grid(row=1,column=8,padx=6,pady=(8,0));ttk.Button(top,text='启动后端',command=self._start_backend).grid(row=1,column=9,padx=6,pady=(8,0));ttk.Button(top,text='串口语音自检',command=self._self_test_voice).grid(row=1,column=10,padx=6,pady=(8,0))
        ttk.Label(top,text='唤醒词').grid(row=2,column=0,sticky='w',pady=(8,0));ttk.Entry(top,textvariable=self.var_wake,width=12).grid(row=2,column=1,padx=6,pady=(8,0),sticky='w');ttk.Label(top,text='休眠词').grid(row=2,column=2,sticky='w',pady=(8,0));ttk.Entry(top,textvariable=self.var_sleep,width=12).grid(row=2,column=3,padx=6,pady=(8,0),sticky='w');ttk.Checkbutton(top,text='语音播报',variable=self.var_tts).grid(row=2,column=4,padx=6,pady=(8,0),sticky='w');ttk.Checkbutton(top,text='播报只讲重点',variable=self.var_con).grid(row=2,column=5,padx=6,pady=(8,0),sticky='w');ttk.Checkbutton(top,text='设备喇叭优先',variable=self.var_device_tts).grid(row=2,column=6,padx=6,pady=(8,0),sticky='w');ttk.Button(top,text='喇叭自检',command=self._self_test_speaker).grid(row=2,column=7,padx=6,pady=(8,0))
        body=ttk.Frame(root);body.pack(fill=tk.BOTH,expand=True,pady=(10,0));body.columnconfigure(0,weight=3);body.columnconfigure(1,weight=2);body.rowconfigure(0,weight=1)
        left=ttk.LabelFrame(body,text='运行日志',padding=8);left.grid(row=0,column=0,sticky='nsew',padx=(0,6));left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1);self.txt_log=tk.Text(left,wrap='word',font=('Consolas',10));self.txt_log.grid(row=0,column=0,sticky='nsew');ys=ttk.Scrollbar(left,orient='vertical',command=self.txt_log.yview);ys.grid(row=0,column=1,sticky='ns');self.txt_log.config(yscrollcommand=ys.set)
        right=ttk.LabelFrame(body,text='AI任务与历史',padding=8);right.grid(row=0,column=1,sticky='nsew');right.rowconfigure(3,weight=1);right.columnconfigure(0,weight=1)
        ttk.Label(right,text='手动指令（例：23床现在重点 / 23床生成文书 / 23床申请医嘱）').grid(row=0,column=0,sticky='w');self.txt_in=tk.Text(right,height=6,wrap='word');self.txt_in.grid(row=1,column=0,sticky='ew',pady=(4,6))
        rb=ttk.Frame(right);rb.grid(row=2,column=0,sticky='ew');ttk.Button(rb,text='发送到 AI Agent',command=self._send).pack(side=tk.LEFT);ttk.Button(rb,text='清空输入',command=lambda:self.txt_in.delete('1.0',tk.END)).pack(side=tk.LEFT,padx=8);ttk.Button(rb,text='手动唤醒',command=self._wake).pack(side=tk.LEFT);ttk.Button(rb,text='手动休眠',command=self._sleep).pack(side=tk.LEFT,padx=8)
        hf=ttk.LabelFrame(right,text='会话历史',padding=6);hf.grid(row=3,column=0,sticky='nsew',pady=(8,0));hf.rowconfigure(0,weight=1);hf.columnconfigure(0,weight=1);self.lst=tk.Listbox(hf);self.lst.grid(row=0,column=0,sticky='nsew');ys2=ttk.Scrollbar(hf,orient='vertical',command=self.lst.yview);ys2.grid(row=0,column=1,sticky='ns');self.lst.config(yscrollcommand=ys2.set);self.lst.bind('<<ListboxSelect>>',self._pick)

    def _log(self,s:str)->None:self.q_ui.put(('log',s))
    def _status(self,s:str)->None:self.q_ui.put(('status',s))
    def _auto_connect_on_start(self)->None:
        if self.ser or not self.auto_connect_enabled:
            return
        port=(self.var_port.get() or '').strip()
        if not port:
            self._log('[auto_connect] 未配置串口，跳过自动连接')
            return
        self._log(f'[auto_connect] 尝试自动连接串口 {port}')
        ok=self._connect(silent=True)
        if ok:
            self.auto_connect_retries=0
            return
        self.auto_connect_retries+=1
        if self.auto_connect_retries<5:
            delay_ms=2000+800*self.auto_connect_retries
            self._log(f'[auto_connect] 第{self.auto_connect_retries}次失败，{delay_ms/1000:.1f}s 后重试')
            self.after(delay_ms,self._auto_connect_on_start)
        else:
            self._status('自动连接失败，请检查 COM 口占用后点击“连接串口”')
            self._log('[auto_connect] 已达到最大重试次数，请手动连接')

    def _drain(self)->None:
        try:
            while True:
                t,p=self.q_ui.get_nowait()
                if t=='log': self.txt_log.insert(tk.END,f'{p}\n'); self.txt_log.see(tk.END)
                elif t=='status': self.var_st.set(str(p))
                elif t=='hist': self._append_hist(p)
        except queue.Empty: pass
        self.after(100,self._drain)

    def _load_cfg(self)->dict[str,Any]:
        if not self.cfgf.exists(): return {}
        try:
            o=json.loads(self.cfgf.read_text(encoding='utf-8'))
            if not isinstance(o,dict):
                return {}
            o['wake']=normalize_keyword(str(o.get('wake',DEFAULT_WAKE)),DEFAULT_WAKE)
            o['sleep']=normalize_keyword(str(o.get('sleep',DEFAULT_SLEEP)),DEFAULT_SLEEP)
            return o
        except Exception: return {}

    def _save_cfg(self)->None:
        self.cfgf.write_text(json.dumps({'port':self.var_port.get().strip(),'baud':self.var_baud.get().strip(),'api':self.var_api.get().strip(),'dep':self.var_dep.get().strip(),'user':self.var_user.get().strip(),'wake':self.var_wake.get().strip(),'sleep':self.var_sleep.get().strip(),'write':bool(self.var_write.get()),'raw':bool(self.var_raw.get()),'tts':bool(self.var_tts.get()),'concise':bool(self.var_con.get()),'device_tts':bool(self.var_device_tts.get())},ensure_ascii=False,indent=2),encoding='utf-8')

    def _ports(self)->None:
        arr=[p.device for p in serial.tools.list_ports.comports()];self.cmb['values']=arr
        if self.var_port.get() not in arr and arr:self.var_port.set(arr[0])
        self._log(f"[ports] {arr or '未发现串口'}")

    def _check(self)->None:
        api=self.var_api.get().strip().rstrip('/')
        try:r=requests.get(f'{api}/health',timeout=6);r.raise_for_status();self._log(f'[gateway] {r.text}');self._status('网关可用')
        except Exception as e:self._log(f'[gateway_error] {e}');self._status('网关不可用');messagebox.showwarning('网关不可用','请先启动后端核心服务。')

    def _gateway_ok(self,api_base:str,timeout:float=2.0)->bool:
        try:
            r=requests.get(f'{api_base}/health',timeout=max(0.8,float(timeout)))
            if not r.ok:
                return False
            body=r.json() if 'application/json' in (r.headers.get('content-type','').lower()) else {}
            if isinstance(body,dict):
                status=str(body.get('status') or '').strip().lower()
                if status:
                    return status=='ok'
            return True
        except Exception:
            return False

    def _launch_backend_script(self)->bool:
        s=self.base/'scripts'/'start_backend_core.ps1'
        if not s.exists():
            self._log(f'[backend_error] 未找到脚本: {s}')
            return False
        try:
            flags=0x08000000 if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
            subprocess.Popen(['powershell','-ExecutionPolicy','Bypass','-File',str(s)],creationflags=flags)
            self.last_backend_start_ts=time.time()
            self._log('[backend] 已触发后端启动，请等待 6~15 秒')
            return True
        except Exception as e:
            self._log(f'[backend_error] {e}')
            return False

    def _wait_gateway_ready(self,api_base:str,timeout_sec:float=BACKEND_READY_TIMEOUT_SEC)->bool:
        deadline=time.time()+max(3.0,float(timeout_sec))
        while time.time()<deadline:
            if self._gateway_ok(api_base,timeout=2.0):
                return True
            time.sleep(1.0)
        return False

    def _ensure_backend_alive(self,reason:str='',force_start:bool=False)->bool:
        api=(self.var_api.get() or '').strip().rstrip('/')
        if not api:
            self._log('[backend_error] API 地址为空')
            return False
        if self._gateway_ok(api,timeout=1.5):
            return True
        with self.backend_bootstrap_lock:
            if self._gateway_ok(api,timeout=1.5):
                return True
            now=time.time()
            can_restart=force_start or ((now-self.last_backend_start_ts) >= BACKEND_RESTART_COOLDOWN_SEC)
            if can_restart:
                if reason:
                    self._log(f'[backend] 网关不可用，准备重启（原因: {reason}）')
                if not self._launch_backend_script():
                    return False
            else:
                self._log('[backend] 网关尚未就绪，沿用最近一次启动并继续等待...')
            ok=self._wait_gateway_ready(api,timeout_sec=BACKEND_READY_TIMEOUT_SEC)
            if ok:
                self._log('[gateway] 后端已就绪')
                return True
            self._log('[gateway_error] 后端启动超时，8000 仍不可用')
            return False

    def _start_backend(self)->None:
        def _run()->None:
            api=(self.var_api.get() or '').strip().rstrip('/')
            if self._gateway_ok(api,timeout=1.8):
                self._log('[backend] 已就绪，无需重复启动')
                self._status('网关可用')
                return
            ok=self._ensure_backend_alive(reason='manual_start',force_start=True)
            self._status('网关可用' if ok else '网关不可用')
            if not ok:
                self.q_ui.put(('log',f'[backend_hint] 请检查 logs/svc_8000.err.log 与 logs/svc_{GATEWAY_PORT}.err.log'))
        threading.Thread(target=_run,daemon=True).start()

    def _bind(self)->None:
        self.var_user.set(DEFAULT_USER);uid=self._ensure_user(DEFAULT_USER);self._log(f'[bind] 已绑定账号: {DEFAULT_USER} -> {uid}');self._status(f'已绑定 {DEFAULT_USER}')

    def _active_private_ipv4(self)->list[str]:
        ips:list[str]=[]
        ps_candidates=[
            (
                "Get-NetIPConfiguration -ErrorAction SilentlyContinue | "
                "Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway -and "
                "$_.InterfaceAlias -notmatch 'Loopback|vEthernet|VMware|Virtual|Hyper-V|Docker|Tailscale' } | "
                "Select-Object -ExpandProperty IPv4Address | Select-Object -ExpandProperty IPAddress"
            ),
            (
                "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                "Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and "
                "$_.InterfaceAlias -notmatch 'Loopback|vEthernet|VMware|Virtual|Hyper-V|Docker|Tailscale' } | "
                "Sort-Object InterfaceMetric,SkipAsSource | Select-Object -ExpandProperty IPAddress"
            ),
        ]
        for cmd in ps_candidates:
            try:
                out=subprocess.check_output(
                    ['powershell','-NoProfile','-Command',cmd],
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=5,
                )
                for line in (out or '').splitlines():
                    ip=(line or '').strip()
                    if not ip:
                        continue
                    try:
                        obj=ipaddress.ip_address(ip)
                        if obj.is_private and (not obj.is_loopback) and (not obj.is_link_local):
                            val=str(obj)
                            if val not in ips:
                                ips.append(val)
                    except Exception:
                        continue
            except Exception:
                continue
        return ips

    @staticmethod
    def _subnet_prefix(ip_text:str)->str:
        ip=(ip_text or '').strip()
        m=re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}$',ip)
        if not m:
            return ''
        return f'{m.group(1)}.{m.group(2)}.{m.group(3)}.'

    def _resolve_lan_ip(self)->str:
        active_ips=self._active_private_ipv4()
        device_prefix=self._subnet_prefix(self.last_device_sta_ip)
        # 先按“设备当前网段”选本机 IP，避免热点切换后继续推旧网段地址。
        if device_prefix:
            matched=[ip for ip in active_ips if ip.startswith(device_prefix)]
            if matched:
                return matched[0]
            now=time.time()
            if now-self.last_subnet_mismatch_warn_ts>8.0:
                self.last_subnet_mismatch_warn_ts=now
                self._log(f'[net_warn] 设备IP={self.last_device_sta_ip}，但本机无同网段IP（active={active_ips}）。请让电脑与设备接入同一热点/Wi-Fi。')

        forced=(FORCED_DEVICE_HOST or '').strip()
        if forced:
            try:
                obj=ipaddress.ip_address(forced)
                if obj.is_loopback or obj.is_link_local:
                    raise ValueError('loopback_or_link_local')
                if forced in set(active_ips):
                    return forced
                self._log(f'[mode_warn] 忽略过期 XIAOYI_DEVICE_HOST={forced}，当前活动网卡未包含该地址')
            except Exception:
                # 域名或外部入口可直接保留
                if re.match(r'^[A-Za-z0-9_.-]+$',forced):
                    return forced

        preferred_prefixes:list[str]=[]
        if device_prefix:
            preferred_prefixes.append(device_prefix)
        for prefix in (PREFERRED_LAN_PREFIX,'192.168.','10.','172.'):
            p=(prefix or '').strip()
            if p and p not in preferred_prefixes:
                preferred_prefixes.append(p)
        for prefix in preferred_prefixes:
            for ip in active_ips:
                if ip.startswith(prefix):
                    return ip
        if active_ips:
            return active_ips[0]

        cands:list[str]=[]
        try:
            # 仅用于兜底：即使没有公网，也可能返回当前默认路由网卡地址
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            s.connect(('8.8.8.8',80))
            ip=s.getsockname()[0]
            s.close()
            if ip:
                cands.append(ip.strip())
        except Exception:
            pass

        try:
            for info in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
                ip=str(info[4][0] if info and info[4] else '').strip()
                if ip:
                    cands.append(ip)
        except Exception:
            pass

        try:
            out=subprocess.check_output(['ipconfig'],text=True,encoding='gbk',errors='ignore')
            cands.extend(re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',out))
        except Exception:
            pass

        good:list[str]=[]
        for ip in cands:
            try:
                obj=ipaddress.ip_address(ip)
                if obj.is_loopback or obj.is_link_local or (not obj.is_private):
                    continue
                val=str(obj)
                if val not in good:
                    good.append(val)
            except Exception:
                continue

        for prefix in (PREFERRED_LAN_PREFIX,'192.168.','10.','172.'):
            for ip in good:
                if ip.startswith(prefix):
                    return ip
        return good[0] if good else '127.0.0.1'

    def _resolve_gateway_host_for_device(self)->str:
        api=(self.var_api.get() or '').strip()
        host=''
        try:
            parsed=urlparse(api)
            host=(parsed.hostname or '').strip()
        except Exception:
            host=''
        if not host or host in ('127.0.0.1','localhost'):
            host=self._resolve_lan_ip()
        return host or '127.0.0.1'

    def _resolve_gateway_port_for_device(self)->int:
        # 默认严格使用当前环境端口，避免多板并行时误连到别的网关实例。
        if STRICT_GATEWAY_PORT:
            return int(GATEWAY_PORT)
        # 非严格模式才允许回退到常见端口。
        candidates=[int(GATEWAY_PORT),8013,19013,29113,8081]
        seen=set()
        dedup=[]
        for p in candidates:
            if p not in seen:
                seen.add(p)
                dedup.append(p)
        for p in dedup:
            try:
                r=requests.get(f'http://127.0.0.1:{p}/health',timeout=1.2)
                if r.ok:
                    return p
            except Exception:
                continue
        return int(GATEWAY_PORT)

    def _count_gateway_sessions(self,port:int)->int:
        try:
            r=requests.get(f'http://127.0.0.1:{port}/api/device/sessions',timeout=1.2)
            r.raise_for_status()
            body=r.json() if isinstance(r.json(),dict) else {}
            count=body.get('count')
            if isinstance(count,int):
                return max(0,count)
            sessions=body.get('sessions')
            if isinstance(sessions,list):
                return len(sessions)
        except Exception:
            pass
        return -1

    def _gateway_session_live_recently(self,now:float|None=None)->bool:
        ts=time.time() if now is None else float(now)
        port=self._resolve_gateway_port_for_device()
        cnt=self._count_gateway_sessions(port)
        if cnt>0:
            self.last_gateway_session_seen_ts=ts
            return True
        return (self.last_gateway_session_seen_ts>0.0) and (ts-self.last_gateway_session_seen_ts<=12.0)

    def _schedule_stt_fallback(self,text:str,stt_ts:float)->None:
        txt=(text or '').strip()
        if not txt:
            return
        def _job()->None:
            time.sleep(2.8)
            if self.stop_w.is_set():
                return
            if self.last_device_tts_ts>=stt_ts:
                return
            # 网关会话不稳定或 TTS 未到达，回退到 host 侧 AI 处理，避免用户“说了没回应”。
            self._log(f'[stt_fallback] 设备侧2.8s未返回TTS，回退本地处理: {txt}')
            self.q_task.put(('serial',txt))
        threading.Thread(target=_job,daemon=True).start()

    def _check_gateway_sessions_for_recover(self,now:float)->None:
        if now-self.last_gateway_session_check_ts<6.0:
            return
        self.last_gateway_session_check_ts=now
        if not self.ser:
            return
        port=self._resolve_gateway_port_for_device()
        cnt=self._count_gateway_sessions(port)
        if cnt>0:
            self.last_gateway_session_seen_ts=now
            return
        if cnt==0 and self.auto_listen_enabled:
            idle_too_long=(self.last_gateway_session_seen_ts<=0.0) or (now-self.last_gateway_session_seen_ts>14.0)
            if idle_too_long and (now-self.last_local_mode_cmd_ts>8.0):
                self._log('[session_recover] 网关暂无设备会话，自动重推本地网关并重入监听。')
                self._enforce_local_mode(force_start=True,reason='no_gateway_session')

    def _sync_device_cloud_settings(self,now:float,force:bool=False)->None:
        host=self._resolve_gateway_host_for_device()
        port=self._resolve_gateway_port_for_device()
        ota=f'http://{host}:{port}/xiaozhi/ota/'
        ws=f'ws://{host}:{port}/xiaozhi/v1/'
        if (not force) and ws==self.last_synced_ws_url and (now-self.last_cloud_sync_ts<300.0):
            return
        if host!=self.last_synced_host:
            self._log(f'[mode] 本机网关地址识别为: {host}')
            self.last_synced_host=host
        if port!=self.last_synced_gateway_port:
            self._log(f'[mode] 网关端口已切换: {self.last_synced_gateway_port} -> {port}')
            self.last_synced_gateway_port=port
        cmds=[
            'XIAOYI_CMD:SET_PROTOCOL:WS',
            f'XIAOYI_CMD:SET_OTA_URL:{ota}',
            f'XIAOYI_CMD:SET_WS_URL:{ws}',
            # 串口高频下发时，个别固件会偶发截断 ws URL（如 ws://19）。
            # 双写一次并拉长间隔，显著降低“握手失败 + sessions=0”概率。
            f'XIAOYI_CMD:SET_WS_URL:{ws}',
            'XIAOYI_CMD:RELOAD_PROTOCOL',
            'XIAOYI_CMD:CLOUD_CONFIG',
        ]
        for c in cmds:
            self._serial_write_line(c)
            time.sleep(0.34)
        self.last_cloud_sync_ts=now
        self.last_synced_ws_url=ws
        self._log(f'[mode] 已自动同步本地网关: {ws}')

    def _enforce_local_mode(self,force_start:bool=False,reason:str='')->None:
        now=time.time()
        mode_interval=22.0 if self.supports_start_listening_cmd is False else 14.0
        active_state=self.device_state in ('listening','speaking','connecting','start_listening','pcm_begin','pcm_end','recording')
        # 避免在活跃监听中反复下发模式命令，导致语音被打断
        need_mode=force_start or ((not active_state) and (now-self.last_local_mode_cmd_ts>=mode_interval))
        if need_mode:
            self._serial_write_line('XIAOYI_CMD:HOST_LOCAL_ONLY_ON')
            self._sync_device_cloud_settings(now,force=force_start)
            self.last_local_mode_cmd_ts=now
            if reason and (now-self.last_mode_log_ts>4.0):
                self.last_mode_log_ts=now
                self._log(f'[mode] 强制小医本地模式：{reason}')
        listen_interval=3.5 if self.device_state in ('idle','stop_listening','auto_stop_listening_silence_3s') else 8.0
        if self.auto_listen_enabled and self.supports_start_listening_cmd is not False and (not active_state) and (force_start or (now-self.last_start_listen_ts>=listen_interval)):
            # 兼容不同固件命令别名，避免停在 idle 导致“说话没反应”
            self._serial_write_line('XIAOYI_CMD:START_LISTENING')
            self._serial_write_line('START_LISTENING')
            self.last_start_listen_ts=now

    def _inspect_serial_raw_line(self,line:str)->None:
        s=(line or '').strip()
        if not s:
            return
        if re.search(r'WS:\s*Session ID:',s,re.IGNORECASE):
            self.last_ws_connected_ts=time.time()
            self.ws_handshake_fail_count=0
        ip_match=re.search(r'(?:sta ip|got ip)\s*:\s*((?:\d{1,3}\.){3}\d{1,3})',s,re.IGNORECASE)
        if ip_match:
            ip=ip_match.group(1).strip()
            if ip and ip!=self.last_device_sta_ip:
                self.last_device_sta_ip=ip
                self._log(f'[net] 设备IP: {ip}')
        low=s.lower()
        if ('websocket handshake failed' in low) or ('failed to connect to websocket server' in low):
            now=time.time()
            if now-self.last_ws_handshake_fail_ts<=6.0:
                self.ws_handshake_fail_count+=1
            else:
                self.ws_handshake_fail_count=1
            self.last_ws_handshake_fail_ts=now
            # 连续失败再恢复，避免串口命令风暴导致 URL 被污染
            if self.ws_handshake_fail_count>=2 and (now-self.last_local_mode_cmd_ts>8.0):
                self._log('[net_recover] 检测到连续 WebSocket 握手失败，自动重推本地网关并重入监听。')
                self._enforce_local_mode(force_start=True,reason='ws_handshake_failed')
            return
        m=re.search(r'AfeWakeWord:\s*Model\s+\d+:\s*([A-Za-z0-9_]+)',s,re.IGNORECASE)
        if not m:
            m=re.search(r'AFE_CONFIG:\s*Set WakeNet Model:\s*([A-Za-z0-9_]+)',s,re.IGNORECASE)
        if m:
            model=(m.group(1) or '').strip()
            if model and model!=self.detected_wake_model:
                self.detected_wake_model=model
                self._log(f'[wake_model] 当前固件唤醒模型：{model}')
                low=model.lower()
                if ('nihaoxiaozhi' in low) and (time.time()-self.last_model_hint_ts>20):
                    self.last_model_hint_ts=time.time()
                    self._log('[wake_hint] 检测到旧版唤醒模型（nihaoxiaozhi），已保持“小医小医”作为上层唤醒词。')
                    self._status('已启用“小医小医”语音唤醒')

    def _wake(self)->None:
        self.awake=True
        self.auto_listen_enabled=True
        self._status('已唤醒：等待语音指令')
        self._log('[voice] 手动唤醒')
        if self.supports_start_listening_cmd is False:
            wk=self.var_wake.get().strip() or '你好小智'
            self._log(f'[voice_hint] 当前固件不支持串口手动进入监听，请先说唤醒词：{wk}')
            self._tts_short(f'请先说{wk}，再说业务指令')
            return
        self._enforce_local_mode(force_start=True,reason='手动唤醒')

    def _sleep(self)->None:
        self.awake=False
        self.auto_listen_enabled=False
        self._status('已休眠：仅响应唤醒词')
        self._log('[voice] 手动休眠')
        self._serial_write_line('XIAOYI_CMD:STOP_LISTENING')
        self._serial_write_line('STOP_LISTENING')
        self._serial_write_line('XIAOYI_CMD:SLEEP')
    def _toggle(self)->None: self._disconnect() if self.ser else self._connect(silent=False)

    def _release_known_com_conflicts(self)->None:
        # 仅清理会抢占 COM5 的旧桥接进程，避免“拒绝访问”
        try:
            this_pid=os.getpid()
            ps_cmd=(
                "Get-CimInstance Win32_Process | Where-Object { "
                "($_.ProcessId -ne %d) -and "
                "($_.CommandLine -like '*xiaozhi_serial_agent_bridge.py*' -or "
                "$_.CommandLine -like '*start_xiaozhi_bridge.ps1*') } | "
                "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; "
                "Write-Output ('killed=' + $_.ProcessId) } catch {} }" % this_pid
            )
            out=subprocess.run(['powershell','-NoProfile','-Command',ps_cmd],capture_output=True,text=True,timeout=8,check=False)
            if out.stdout and out.stdout.strip():
                self._log(f"[serial_guard] 已清理抢占串口进程: {out.stdout.strip()}")
        except Exception:
            pass

    def _connect(self,silent:bool=False)->bool:
        port=self.var_port.get().strip();bt=self.var_baud.get().strip()
        if not port:
            if not silent:
                messagebox.showwarning('提示','请选择串口。')
            return False
        try:
            baud=int(bt)
        except ValueError:
            if not silent:
                messagebox.showwarning('提示','波特率必须是整数。')
            return False
        self._release_known_com_conflicts()
        try:
            self.ser=serial.Serial(port,baud,timeout=1.0,dsrdtr=False,rtscts=False)
            try:
                self.ser.setDTR(False);self.ser.setRTS(False)
            except Exception:
                pass
            self.stop_s.clear();self.s_thread=threading.Thread(target=self._serial_loop,daemon=True);self.s_thread.start();self.btn_conn.config(text='断开串口');self._status(f'串口已连接: {port}');self._log(f'[serial] connected {port} @ {baud}')
            time.sleep(0.08)
            self.supports_xiaoyi_cmd=False
            self._serial_write_line('XIAOYI_CMD:PING')
            self.auto_listen_enabled=True
            self.supports_start_listening_cmd=None
            threading.Thread(target=lambda:self._ensure_backend_alive(reason='serial_connect'),daemon=True).start()
            self._enforce_local_mode(force_start=True,reason='串口连接')
            self._probe_protocol_support()
            self._save_cfg()
            return True
        except Exception as e:
            self.ser=None;self._log(f'[serial_error] {e}')
            msg=str(e)
            if 'PermissionError' in msg or '拒绝访问' in msg:
                msg='串口被其他程序占用（例如串口监视器/旧桥接脚本）。请先关闭占用 COM5 的程序后重试。'
            if silent:
                self._status(f'自动连接失败: {msg}')
            else:
                messagebox.showerror('串口连接失败',msg)
            return False

    def _probe_protocol_support(self)->None:
        started=time.time()
        self.last_start_probe_ts=started
        # 先探测一次 START_LISTENING，判定是否支持串口手动进 listening
        self._serial_write_line('XIAOYI_CMD:START_LISTENING')
        def _watch()->None:
            deadline=started+6.0
            while time.time()<deadline and not self.supports_xiaoyi_cmd:
                time.sleep(0.18)
            if self.supports_xiaoyi_cmd:
                self.q_ui.put(('status','小医串口协议已就绪'))
            else:
                if time.time()-self.last_proto_warn_ts>15:
                    self.last_proto_warn_ts=time.time()
                    self.q_ui.put(('log','[proto_warn] 未收到 XIAOYI_CMD:PING 回应（serial_pong）。当前可能是原版固件，建议先刷 xiaoyi_esp32s3 固件。'))
                    self.q_ui.put(('status','未检测到小医协议（建议刷小医固件）'))
            # 再看 START_LISTENING 是否得到状态确认。
            # 部分固件在刚联网/激活时会延后进入 listening，这里延长窗口并重试命令，避免误判。
            for _ in range(3):
                if self.supports_start_listening_cmd is not None:
                    break
                self._serial_write_line('XIAOYI_CMD:START_LISTENING')
                self._serial_write_line('START_LISTENING')
                time.sleep(0.6)
            deadline2=time.time()+6.5
            while time.time()<deadline2 and self.supports_start_listening_cmd is None:
                time.sleep(0.12)
            if self.supports_start_listening_cmd is None:
                self.supports_start_listening_cmd=False
                self.q_ui.put(('log','[listen_probe] 未检测到 start_listening 状态回包：已切换到“唤醒词驱动模式”（先说唤醒词再下达指令）。'))
                self.q_ui.put(('status','唤醒词模式：先说唤醒词'))
            elif self.supports_start_listening_cmd:
                self.q_ui.put(('log','[listen_probe] 检测到 start_listening 支持：可用“手动唤醒”按钮。'))
        threading.Thread(target=_watch,daemon=True).start()

    def _disconnect(self)->None:
        self.stop_s.set()
        with self.lock:
            try:
                if self.ser:self.ser.close()
            except Exception:pass
            self.ser=None
        self.btn_conn.config(text='连接串口');self._status('串口已断开');self._log('[serial] disconnected')

    def _send(self)->None:
        t=self.txt_in.get('1.0',tk.END).strip()
        if not t: messagebox.showinfo('提示','请输入指令内容。'); return
        self.q_task.put(('manual',t));self._log(f'[manual] queued: {t}')

    def _serial_loop(self)->None:
        while not self.stop_s.is_set():
            conn=self.ser
            if not conn:break
            try:
                waiting=0
                try:
                    waiting=int(conn.in_waiting or 0)
                except Exception:
                    waiting=0
                raw=conn.read(waiting or 1)
                if not raw:
                    # idle heartbeat: avoid spamming START_LISTENING during silence
                    now=time.time()
                    if now-self.last_local_mode_cmd_ts>=25.0:
                        self._enforce_local_mode(force_start=False,reason='idle_keepalive')
                    self._check_gateway_sessions_for_recover(now)
                    continue
                self.serial_rx_buffer.extend(raw)
                while True:
                    nl=self.serial_rx_buffer.find(b'\n')
                    if nl<0:
                        if len(self.serial_rx_buffer)>131072:
                            self._log(f'[serial_warn] dropped oversized partial buffer {len(self.serial_rx_buffer)} bytes')
                            self.serial_rx_buffer.clear()
                        break
                    line_bytes=bytes(self.serial_rx_buffer[:nl])
                    del self.serial_rx_buffer[:nl+1]
                    line=decode_serial_line_bytes(line_bytes).strip('\r').strip()
                    if not line:continue
                    self._inspect_serial_raw_line(line)
                    if self.var_raw.get():self._log(f'[raw] {line}')
                    ev=parse_xiaozhi_event(line)
                    if ev is not None:
                        self._on_xiaozhi_event(ev[0],ev[1],line)
                        continue
                    if self.serial_audio_streaming:
                        payload=''
                        # 1) 直接 chunk 协议
                        if line.upper().startswith('XIAOYI_PCM16LE_CHUNK:'):
                            payload=line.split(':',1)[1].strip()
                        else:
                            # 2) 日志封装事件：... AUDIO_CHUNK:xxxx
                            m_evt=re.search(r'AUDIO_CHUNK\s*:\s*([A-Za-z0-9+/=]{24,})\s*$',line,re.IGNORECASE)
                            if m_evt:
                                payload=(m_evt.group(1) or '').strip()
                            else:
                                # 3) 纯裸 base64 行（仅允许整行都为 base64）
                                if re.fullmatch(r'[A-Za-z0-9+/=]{24,}',line):
                                    payload=line
                        clean=sanitize_base64_text(payload)
                        if clean and len(clean)>=24 and re.fullmatch(r'[A-Za-z0-9+/=]{24,}',clean):
                            self.serial_audio_chunks.append(clean)
                        # 录音流期间，非 chunk 行不进入文本问答链路，避免日志污染 AI 输入
                        continue
                    txt=extract_text(line)
                    if not txt:continue
                    self._serial_text(txt)
            except Exception as e:
                self._log(f'[serial_error] {e}')
                if self._try_reconnect_serial():
                    continue
                self._status('串口读取异常');break
        self._disconnect()

    def _try_reconnect_serial(self)->bool:
        if self.stop_s.is_set():
            return False
        port=self.var_port.get().strip()
        try:baud=int(self.var_baud.get().strip())
        except Exception:return False
        if not port:return False
        self._status('串口异常，尝试自动重连...')
        for i in range(1,4):
            if self.stop_s.is_set():
                return False
            time.sleep(0.5*i)
            try:
                with self.lock:
                    if self.ser:
                        try:self.ser.close()
                        except Exception:pass
                    self.ser=serial.Serial(port,baud,timeout=1.0,dsrdtr=False,rtscts=False)
                    try:
                        self.ser.setDTR(False);self.ser.setRTS(False)
                    except Exception:
                        pass
                self._log(f'[serial] auto-reconnected {port} @ {baud} (try {i})')
                self._status(f'串口已重连: {port}')
                self.auto_listen_enabled=True
                self.supports_start_listening_cmd=None
                self._enforce_local_mode(force_start=True,reason='串口重连')
                self._probe_protocol_support()
                return True
            except Exception as e:
                self._log(f'[serial_reconnect_fail] try {i}: {e}')
        return False

    def _on_xiaozhi_event(self,kind:str,payload:str,raw_line:str)->None:
        if kind=='audio_begin':
            try:self.serial_audio_sr=max(8000,int((payload or '16000').split(':',1)[0].strip() or '16000'))
            except Exception:self.serial_audio_sr=16000
            self.serial_audio_streaming=True
            self.serial_audio_chunks.clear()
            self._log(f'[serial_audio] begin sr={self.serial_audio_sr}')
            self._status('设备语音上传中...')
            return
        if kind=='audio_chunk':
            if self.serial_audio_streaming and payload and payload!='-':
                clean=sanitize_base64_text(payload)
                if clean:
                    self.serial_audio_chunks.append(clean)
            return
        if kind=='audio_end':
            sample_count='0';state='ok'
            if payload and payload!='-':
                parts=payload.split(':')
                if parts: sample_count=parts[0].strip() or '0'
                if len(parts)>1: state=parts[1].strip() or 'ok'
            chunk_count=len(self.serial_audio_chunks)
            self._log(f'[serial_audio] end samples={sample_count}, state={state}, chunks={chunk_count}')
            if self.serial_audio_streaming and chunk_count>0:
                self.q_task.put(('serial_audio',{'sample_rate':self.serial_audio_sr,'chunks':self.serial_audio_chunks.copy(),'sample_count':sample_count,'state':state}))
            else:
                self._log('[serial_audio_warn] 设备结束上传，但未收到有效音频块')
                self._status('未收到有效语音数据')
            self.serial_audio_streaming=False
            self.serial_audio_chunks.clear()
            return
        if kind=='audio_level':
            parts=[p.strip() for p in str(payload or '').split(':')]
            avg=parts[0] if len(parts)>0 else '-'
            peak=parts[1] if len(parts)>1 else '-'
            buffered=parts[2] if len(parts)>2 else '-'
            self._log(f'[audio_level] avg={avg}, peak={peak}, buffered={buffered}')
            return
        shown=visible_name(payload)
        self.last_voice_event_ts=time.time();self.last_voice_event_kind=kind;self.last_voice_event_payload=shown or payload
        if kind=='state':
            self._log(f'[xiaoyi_state] {shown or payload}')
            p=(payload or "").strip().lower()
            if p in ('serial_pong','pong'):
                self.supports_xiaoyi_cmd=True
            if p in ('start_listening','stop_listening'):
                self.supports_start_listening_cmd=True
            self.device_state=p or self.device_state
            if p=='pcm_begin':
                self.serial_audio_streaming=True
                self.serial_audio_chunks.clear()
                self.serial_audio_sr=16000
                self.awake=True
                self._log('[serial_audio] begin(state pcm_begin)')
                self._status('设备语音上传中...')
                return
            if p=='pcm_end':
                chunk_count=len(self.serial_audio_chunks)
                self._log(f'[serial_audio] end(state pcm_end), chunks={chunk_count}')
                if self.serial_audio_streaming and chunk_count>0:
                    self.q_task.put(('serial_audio',{'sample_rate':self.serial_audio_sr,'chunks':self.serial_audio_chunks.copy(),'sample_count':'-','state':'ok'}))
                else:
                    self._log('[serial_audio_warn] pcm_end 到达，但未收到有效音频块')
                    self._status('未收到有效语音数据')
                self.serial_audio_streaming=False
                self.serial_audio_chunks.clear()
                return
            if p in ('listening','start_listening','connecting'):
                self.awake=True
            elif p in ('stop_listening','idle'):
                self.awake=False
            if self.auto_listen_enabled:
                if p in ('idle','stop_listening','auto_stop_listening_silence_3s'):
                    # idle 后立即重入 listening，但不强制重载协议，避免把刚录的音频会话打断。
                    self._enforce_local_mode(force_start=False,reason=f'state={p}')
                    now=time.time()
                    if self.supports_start_listening_cmd is not False and (now-self.last_start_listen_ts>=1.8):
                        self._serial_write_line('XIAOYI_CMD:START_LISTENING')
                        self._serial_write_line('START_LISTENING')
                        self.last_start_listen_ts=now
                elif p in ('activating',):
                    # 激活阶段仅做配置保活，不抢占状态机。
                    self._enforce_local_mode(force_start=False,reason=f'state={p}')
            return
        if kind=='wake':
            self.awake=True;self._status('设备已唤醒：监听中');self._log(f'[xiaoyi_wake] {shown or payload}')
            if self.auto_listen_enabled:
                self._enforce_local_mode(force_start=False)
            return
        if kind=='stt':
            self.awake=True;text=(shown or payload).strip()
            if not text:return
            if self._is_failed_asr_result(text,'device'):
                self._log(f'[xiaoyi_stt_warn] 设备返回无效转写，已忽略: {text}')
                self._status('语音转写失败，请再说一遍')
                return
            now=time.time()
            if text==self.last_device_stt_text and (now-self.last_device_stt_ts<=1.8):
                self._log(f'[xiaoyi_stt_skip] 忽略重复转写: {text}')
                return
            self.last_device_stt_text=text
            self.last_device_stt_ts=now
            self._log(f'[xiaoyi_stt] {text}')
            if (not REPROCESS_DEVICE_STT) and self._gateway_session_live_recently(now):
                # WebSocket 模式下，设备网关已经在后台跑完整 AI 流水线，
                # 这里不再把 STT 二次送入 host 侧 AI，避免重复处理和排队变慢。
                self._status('已识别语音，等待设备端AI回包...')
                self._schedule_stt_fallback(text,now)
                return
            self.q_task.put(('serial',text))
            return
        if kind=='tts':
            self.last_device_tts_ts=time.time()
            self._log(f'[xiaoyi_tts] {shown or payload}')
            if ('小智' in payload or '你好小智' in payload) and (time.time()-self.last_xiaozhi_notice_ts>20):
                self.last_xiaozhi_notice_ts=time.time()
                self._status('检测到旧云端话术，正在强制切回小医本地模式')
                self._log('[mode_hint] 检测到旧云端回包，已自动重新切换到本地小医模式。')
                self._serial_write_line('XIAOYI_CMD:STOP_LISTENING')
                self._enforce_local_mode(force_start=True,reason='检测到旧云端话术')
            return
        self._log(f'[serial_event] {kind}: {shown or payload} | {raw_line}')

    def _serial_text(self,txt:str)->None:
        wake=repair_text((self.var_wake.get() or DEFAULT_WAKE).strip()) or DEFAULT_WAKE
        sleep=repair_text((self.var_sleep.get() or DEFAULT_SLEEP).strip()) or DEFAULT_SLEEP
        s=repair_text(txt)
        if self._is_failed_asr_result(s,'device'):
            self._log(f'[serial_text_skip] 忽略无效语音文本: {s}')
            return
        valid_chars=len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',s))
        if valid_chars<2:
            self._log(f'[serial_text_skip] 忽略低质量文本: {s}')
            return
        wakes=[]
        for w in (wake,'小医小医','你好小医','hi小医','Hi小医','嗨小医'):
            ww=(w or '').strip()
            if ww and ww not in wakes:wakes.append(ww)
        if sleep and contains_keyword(s,sleep):
            self.awake=False
            self.auto_listen_enabled=False
            self._status('已休眠：设备进入低功耗')
            self._log(f'[voice] 收到休眠词: {s}')
            self._serial_write_line('XIAOYI_CMD:STOP_LISTENING')
            self._serial_write_line('STOP_LISTENING')
            self._serial_write_line('XIAOYI_CMD:SLEEP')
            self._tts_short('收到，进入休眠。')
            return
        for wk in wakes:
            if contains_keyword(s,wk):
                self.awake=True;remain=strip_wake_from_text(s,wk);self._status('已唤醒：正在监听')
                if remain:self._log(f'[voice] 唤醒并识别: {remain}');self.q_task.put(('serial',remain))
                else:self._log('[voice] 已唤醒，等待下一句');self._tts_short('我在，请讲。')
                return
        if not self.awake:
            self._log(f'[voice] 休眠中，忽略: {s}');return
        self._log(f'[serial_text] {s}');self.q_task.put(('serial',s))

    def _worker(self)->None:
        while not self.stop_w.is_set():
            try:src,text=self.q_task.get(timeout=0.2)
            except queue.Empty:continue
            try:
                if src=='serial_audio':
                    self._process_serial_audio(text)
                else:
                    self._process(src,text)
            except Exception as e:self._log(f'[worker_error] {e}')

    def _pcm16le_to_wav_base64(self,pcm_bytes:bytes,sample_rate:int)->str:
        bio=io.BytesIO()
        with wave.open(bio,'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate or 16000)
            wf.writeframes(pcm_bytes)
        return base64.b64encode(bio.getvalue()).decode('ascii')

    def _prepare_pcm_for_asr(self,pcm_bytes:bytes)->bytes:
        try:
            samples=array.array('h')
            samples.frombytes(pcm_bytes)
        except Exception:
            return pcm_bytes
        if not samples:
            return pcm_bytes
        mean=int(sum(int(x) for x in samples)/len(samples))
        peak=max(abs(int(x)-mean) for x in samples) or 1
        scale=1.0
        if peak<6000:
            scale=min(4.0,14000.0/peak)
        elif peak>22000:
            scale=max(0.35,16000.0/peak)
        if abs(mean)>150:
            for i,v in enumerate(samples):
                centered=int(v)-mean
                samples[i]=max(-32768,min(32767,centered))
        if scale!=1.0:
            for i,v in enumerate(samples):
                adjusted=int(round(int(v)*scale))
                samples[i]=max(-32768,min(32767,adjusted))
        return samples.tobytes()

    def _save_serial_audio_debug(self,wav_bytes:bytes,label:str)->Path|None:
        try:
            HOST_LOG_DIR.mkdir(parents=True,exist_ok=True)
            path=HOST_LOG_DIR/f'serial_capture_{label}.wav'
            path.write_bytes(wav_bytes)
            return path
        except Exception as e:
            self._log(f'[serial_audio_warn] 保存 {label} wav 失败: {e}')
            return None

    def _is_failed_asr_result(self,text:str,provider:str)->bool:
        t=repair_text(text).strip()
        low=t.lower()
        if provider in ('fallback','mock-funasr'):
            return True
        bad_markers=(
            '语音转写失败',
            '未识别到语音',
            '未识别到清晰语音',
            '请重试',
            '请再说一遍',
            '手动输入',
            '中文普通话护理场景问答',
            '无法听到您的话语',
        )
        return any(mark in t for mark in bad_markers) or '璇' in low

    def _process_serial_audio(self,payload:Any)->None:
        if not isinstance(payload,dict):
            self._log('[serial_audio_error] payload 不是字典')
            return
        chunks=payload.get('chunks') if isinstance(payload.get('chunks'),list) else []
        if not chunks:
            self._log('[serial_audio_warn] 没有音频块可供转写')
            self._status('语音为空')
            return
        sample_rate=int(payload.get('sample_rate') or 16000)
        clean_chunks=[sanitize_base64_text(x) for x in chunks]
        joined=''.join(x for x in clean_chunks if x)
        if not joined:
            self._log('[serial_audio_warn] 音频块为空字符串')
            self._status('语音为空')
            return
        pad=(-len(joined)) % 4
        if pad:
            joined=joined+('='*pad)
        try:
            pcm_bytes=base64.b64decode(joined,validate=False)
        except Exception as e:
            self._log(f'[serial_audio_error] base64 解码失败: {e}')
            self._status('语音数据损坏')
            return
        if len(pcm_bytes)<320:
            self._log(f'[serial_audio_warn] PCM 过短: {len(pcm_bytes)} bytes')
            self._status('语音过短')
            return
        raw_wav_bytes=base64.b64decode(self._pcm16le_to_wav_base64(pcm_bytes,sample_rate),validate=False)
        raw_saved=self._save_serial_audio_debug(raw_wav_bytes,'latest_raw')
        pcm_for_asr=self._prepare_pcm_for_asr(pcm_bytes)
        wav_b64=self._pcm16le_to_wav_base64(pcm_for_asr,sample_rate)
        wav_bytes=base64.b64decode(wav_b64,validate=False)
        norm_saved=self._save_serial_audio_debug(wav_bytes,'latest_norm')
        api=self.var_api.get().strip().rstrip('/')
        self._status('语音转写中...')
        self._log(f'[serial_audio] bytes={len(pcm_bytes)}, sr={sample_rate}')
        if raw_saved:self._log(f'[serial_audio] 原始音频已保存: {raw_saved}')
        if norm_saved:self._log(f'[serial_audio] 归一化音频已保存: {norm_saved}')
        try:
            self._status('本地语音转写中...')
            local_text,local_conf,local_provider=transcribe_local_wav_bytes(wav_bytes)
            self._log(f'[asr_local] provider={local_provider}, confidence={local_conf}, text={local_text or "(empty)"}')
            if local_text and (not self._is_failed_asr_result(local_text,local_provider)):
                self._process('serial',local_text)
                return
        except Exception as e:
            self._log(f'[asr_local_error] {e}')
        try:
            r=requests.post(f'{api}/api/asr/transcribe',json={'audio_base64':wav_b64,'request_id':f'serial-{int(time.time()*1000)}'},timeout=50)
            r.raise_for_status()
            body=r.json() if isinstance(r.json(),dict) else {}
        except Exception as e:
            self._log(f'[asr_error] {e}')
            self._status('语音转写失败')
            return
        text=repair_text(str(body.get('text') or '').strip())
        provider=str(body.get('provider') or '').strip()
        confidence=body.get('confidence')
        self._log(f'[asr] provider={provider or "-"}, confidence={confidence}, text={text or "(empty)"}')
        if not text:
            self._status('未识别到语音')
            return
        if self._is_failed_asr_result(text,provider):
            self._status('语音转写失败')
            self._log('[asr] 转写失败结果已拦截，不再送入 AI')
            return
        self._process('serial',text)

    def _process(self,src:str,text:str)->None:
        text=repair_text(text)
        api=self.var_api.get().strip().rstrip('/');dep=self.var_dep.get().strip() or 'dep-card-01';uid=self._ensure_user(self._uid(self.var_user.get().strip() or DEFAULT_USER))
        cfg=Cfg(api=api,dep=dep,uid=uid,write_back=bool(self.var_write.get()),tts=bool(self.var_tts.get()),concise=bool(self.var_con.get()))
        self._ensure_backend_alive(reason='task_dispatch')
        self._status('AI处理中...');self._log(f'[task] source={src} user={uid} text={text}')
        beds=bed_candidates(text)
        pid,bn=resolve_patient(api,dep,text)
        if (not bn) and beds:
            bn=beds[0]
        d=self._direct(cfg,text,pid,bn)
        if d is None:
            # 默认走全量 AI Agent，不再要求固定格式。
            # 无床号时仍可回答通用问题；有床号时自动叠加患者上下文。
            pl={
                'mode':'agent_cluster',
                'cluster_profile':'nursing_default_cluster',
                'department_id':dep,
                'patient_id':pid,
                'bed_no':bn,
                'user_input':text,
                'requested_by':uid,
                'attachments':[],
                'conversation_id':f'voice-{uid}',
                'meta_bed_candidates':beds,
            }
            try:
                data=None
                last_err=None
                for attempt in range(2):
                    try:
                        r=requests.post(f'{api}/api/ai/chat',json=pl,timeout=70)
                        r.raise_for_status()
                        data=r.json()
                        break
                    except Exception as e:
                        last_err=e
                        if attempt==0:
                            self._log(f'[agent_retry] 首次失败，尝试拉起后端后重试: {e}')
                            self._ensure_backend_alive(reason='api_ai_chat_retry')
                            time.sleep(0.4)
                if data is None and last_err is not None:
                    raise last_err
            except Exception as e:
                self._log(f'[agent_error] {e}')
                data={
                    'summary':'后端 AI 暂时不可用，我已记录本次语音请求。请稍后再试，或先问我离线问题。',
                    'findings':['api/ai/chat 调用失败'],
                    'recommendations':[{'title':f'确认后端服务 8000/{GATEWAY_PORT} 是否健康', 'priority':1}],
                    'confidence':0.25,
                    'review_required':True,
                }
            summary=norm(str(data.get('summary') or ''));findings=data.get('findings') if isinstance(data.get('findings'),list) else [];recs=data.get('recommendations') if isinstance(data.get('recommendations'),list) else [];conf=float(data.get('confidence',0.7) or 0.7);review=bool(data.get('review_required',True))
        else:
            summary=norm(str(d.get('summary') or ''));findings=d.get('findings') if isinstance(d.get('findings'),list) else [];recs=d.get('recommendations') if isinstance(d.get('recommendations'),list) else [];conf=float(d.get('confidence',0.8) or 0.8);review=bool(d.get('review_required',True))
        self._log(f'[agent] confidence={conf}, review_required={review}');self._log(f'[agent_summary]\n{summary}')
        b=brief(summary,findings,recs);self._log(f'[voice_brief] {b}')
        row={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'source':src,'input':text,'bed_no':bn,'patient_id':pid,'summary':summary,'brief':b,'confidence':conf,'review_required':review,'requested_by':uid};self._save_hist(row);self.q_ui.put(('hist',row))
        if cfg.tts:self._tts(cfg,b if cfg.concise else summary[:260])
        if cfg.write_back:
            self._serial_write_line(json.dumps({'ok':True,'summary':summary,'brief':b,'confidence':conf,'review_required':review},ensure_ascii=False));self._log('[serial_write] AI结果已回写')
        if self.auto_listen_enabled:
            # 完成一轮任务后自动回到监听，支持连续语音工作流
            self._enforce_local_mode(force_start=True,reason='任务完成，恢复监听')
        self._status('AI处理完成')

    def _direct(self,cfg:Cfg,text:str,pid:str|None,bn:str|None)->dict[str,Any]|None:
        s=text.strip()
        if any(k in s for k in ('生成文书','写文书','护理记录','写护理记录')):
            if not pid:return {'summary':'未定位到病例。请在指令中带床号，例如：23床生成文书。','findings':['缺少患者定位信息'],'recommendations':[{'title':'补充床号后重试','priority':1}],'confidence':0.55,'review_required':True}
            r=requests.post(f'{cfg.api}/api/document/draft',json={'patient_id':pid,'document_type':'nursing_note','spoken_text':s,'requested_by':cfg.uid},timeout=30);r.raise_for_status();it=r.json();did=str(it.get('id') or '')
            return {'summary':f'已为{bn or "该"}床生成护理文书草稿，草稿ID：{did}。可到手机端【文书】页面编辑与提交。','findings':[f'patient_id={pid}'],'recommendations':[{'title':'提交前请人工复核','priority':1}],'confidence':0.88,'review_required':True}
        if any(k in s for k in ('医嘱请求','申请医嘱','请求医嘱','开立医嘱')):
            if not pid:return {'summary':'未定位到病例。请在指令中带床号，例如：23床申请医嘱。','findings':['缺少患者定位信息'],'recommendations':[{'title':'补充床号后重试','priority':1}],'confidence':0.56,'review_required':True}
            pr='P1' if re.search(r'紧急|立即|危急|马上',s) else 'P2';r=requests.post(f'{cfg.api}/api/orders/request',json={'patient_id':pid,'requested_by':cfg.uid,'title':f'{bn or ""}床语音发起医嘱请求'.strip(),'details':s,'priority':pr},timeout=30);r.raise_for_status();it=r.json();ono=str(it.get('order_no') or it.get('id') or '')
            return {'summary':f'已创建医嘱请求：{ono}（{pr}）。可在手机端【医嘱】页进行核对和执行。','findings':[f'patient_id={pid}'],'recommendations':[{'title':'请医生复核后执行','priority':1}],'confidence':0.9,'review_required':True}
        if any(k in s for k in ('查看医嘱','医嘱列表','待执行医嘱','医嘱情况')):
            if not pid:return {'summary':'未定位到病例。请在指令中带床号，例如：23床查看医嘱。','findings':['缺少患者定位信息'],'recommendations':[{'title':'补充床号后重试','priority':1}],'confidence':0.58,'review_required':False}
            r=requests.get(f'{cfg.api}/api/orders/patients/{pid}',timeout=20);r.raise_for_status();body=r.json() if isinstance(r.json(),dict) else {};st=body.get('stats') if isinstance(body.get('stats'),dict) else {};p=int(st.get('pending',0) or 0);d=int(st.get('due_30m',0) or 0);o=int(st.get('overdue',0) or 0)
            return {'summary':f'{bn or "该"}床当前医嘱：待执行{p}条，30分钟内到期{d}条，已超时{o}条。','findings':[f'pending={p}',f'due_30m={d}',f'overdue={o}'],'recommendations':[{'title':'优先处理到期和超时医嘱','priority':1}],'confidence':0.87,'review_required':False}
        return None

    def _tts_short(self,text:str)->None:
        if not text.strip():return
        cfg=Cfg(api=self.var_api.get().strip().rstrip('/'),dep=self.var_dep.get().strip() or 'dep-card-01',uid=self._uid(self.var_user.get().strip() or DEFAULT_USER),write_back=bool(self.var_write.get()),tts=True,concise=True)
        self._tts(cfg,text.strip())

    def _tts(self,cfg:Cfg,text:str)->None:
        spoken=text.strip()
        if not spoken:return
        provider='unknown'
        audio_b64=''
        self._ensure_backend_alive(reason='tts_request')
        try:
            r=None
            for attempt in range(2):
                try:
                    r=requests.post(f'{cfg.api}/api/tts/speak',json={'text':spoken,'voice':'xiaoyi'},timeout=20)
                    break
                except Exception as e:
                    if attempt==0:
                        self._log(f'[tts_retry] 首次失败，尝试拉起后端后重试: {e}')
                        self._ensure_backend_alive(reason='tts_retry')
                        time.sleep(0.35)
                    else:
                        raise
            if r is None:
                raise RuntimeError('tts response is empty')
            if r.ok:
                b=r.json() if isinstance(r.json(),dict) else {}
                provider=str(b.get('provider') or 'unknown')
                audio_b64=str(b.get('audio_base64') or '').strip()
                self._log(f"[tts] provider={provider}")
            else:self._log(f'[tts_error] status={r.status_code} body={r.text[:180]}')
        except Exception as e:self._log(f'[tts_error] {e}')
        if bool(self.var_device_tts.get()):
            if self._tts_device(spoken,audio_b64=audio_b64):
                self._log('[tts_device] 设备喇叭播报命令已发送')
                return
            self._log('[tts_device_warn] 当前固件未确认接收串口播报命令，已回退本机播报。若要设备喇叭播报 AI 结果，需要支持串口播报协议的固件。')
        try:
            ps=("Add-Type -AssemblyName System.Speech;""$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;""$s.Rate = 0;""$s.Volume = 100;""$t=[Console]::In.ReadToEnd();""$s.Speak($t);")
            flags=0x08000000 if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
            subprocess.run(['powershell','-NoProfile','-Command',ps],input=spoken,text=True,timeout=25,creationflags=flags,check=False)
            self._log(f'[tts_local] 本机语音播报完成 provider={provider}')
        except Exception as e:self._log(f'[tts_local_error] {e}')

    def _tts_device(self,text:str,audio_b64:str='')->bool:
        spoken=text.strip()
        if not spoken or not self.ser:
            return False
        start_ts=self.last_voice_event_ts
        if audio_b64 and not audio_b64.startswith('TU9DS19BVURJT19EQVRB'):
            try:
                if self._tts_device_pcm_base64(audio_b64,start_ts):
                    return True
            except Exception as e:
                self._log(f'[tts_device_pcm_error] {e}')
        if self._tts_device_pcm_from_text(spoken,start_ts):
            return True
        if self._tts_device_text_command(spoken,start_ts):
            return True
        return False

    def _tts_device_text_command(self,spoken:str,start_ts:float)->bool:
        cmds=[
            f"XIAOYI_CMD:SPEAK_TEXT:{spoken}",
            f"TTS:{spoken}",
            json.dumps({"type":"tts","state":"sentence_start","text":spoken},ensure_ascii=False),
            json.dumps({"cmd":"tts","text":spoken},ensure_ascii=False),
            json.dumps({"op":"tts","text":spoken},ensure_ascii=False),
        ]
        for cmd in cmds:
            self._serial_write_line(cmd)
            time.sleep(0.05)
        return self._wait_device_tts_ack(start_ts,2.6)

    def _tts_device_pcm_base64(self,audio_b64:str,start_ts:float)->bool:
        raw=base64.b64decode(audio_b64.encode('utf-8'),validate=False)
        if not raw:
            return False
        pcm=None
        sr=24000
        with tempfile.NamedTemporaryFile(delete=False,suffix='.wav') as f:
            f.write(raw);tmp=f.name
        try:
            pcm,sr=self._wav_to_pcm16le(tmp)
        finally:
            try: os.remove(tmp)
            except Exception: pass
        if not pcm:
            return False
        self._serial_send_pcm16(pcm,sr)
        return self._wait_device_tts_ack(start_ts,3.0)

    def _tts_device_pcm_from_text(self,spoken:str,start_ts:float)->bool:
        wav_path=''
        try:
            fd,wav_path=tempfile.mkstemp(prefix='xiaoyi_tts_',suffix='.wav')
            os.close(fd)
            safe_wav=wav_path.replace("'","''")
            ps=(
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.Rate=0;$s.Volume=100;"
                f"$s.SetOutputToWaveFile('{safe_wav}');"
                "$t=[Console]::In.ReadToEnd();$s.Speak($t);$s.Dispose();"
            )
            flags=0x08000000 if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
            subprocess.run(['powershell','-NoProfile','-Command',ps],input=spoken,text=True,timeout=28,creationflags=flags,check=False)
            if not os.path.exists(wav_path) or os.path.getsize(wav_path)<256:
                return False
            pcm,sr=self._wav_to_pcm16le(wav_path)
            if not pcm:
                return False
            self._serial_send_pcm16(pcm,sr)
            return self._wait_device_tts_ack(start_ts,3.2)
        except Exception as e:
            self._log(f'[tts_device_pcm_from_text_error] {e}')
            return False
        finally:
            if wav_path:
                try: os.remove(wav_path)
                except Exception: pass

    def _serial_send_pcm16(self,pcm_bytes:bytes,sample_rate:int)->None:
        if not pcm_bytes:
            return
        sr=int(sample_rate or 24000)
        if sr<8000 or sr>48000:
            sr=24000
        self._serial_write_line(f'XIAOYI_PCM16LE_BEGIN:{sr}')
        # ESP32 串口行解析对超长 base64 行不稳定，使用小分片可避免丢包/截断
        chunk=512
        total=len(pcm_bytes)
        sent=0
        while sent<total:
            part=pcm_bytes[sent:sent+chunk]
            b64=base64.b64encode(part).decode('ascii')
            self._serial_write_line(f'XIAOYI_PCM16LE_CHUNK:{b64}')
            sent+=len(part)
            time.sleep(0.004)
        self._serial_write_line('XIAOYI_PCM16LE_END')

    def _wav_to_pcm16le(self,wav_path:str)->tuple[bytes,int]:
        with wave.open(wav_path,'rb') as wf:
            ch=wf.getnchannels()
            sw=wf.getsampwidth()
            sr=wf.getframerate()
            raw=wf.readframes(wf.getnframes())
        if sw==1:
            # 8bit unsigned -> 16bit signed
            data=bytearray()
            for b in raw:
                v=((int(b)-128)<<8)
                data.extend(int(v).to_bytes(2,'little',signed=True))
            raw=bytes(data);sw=2
        if sw!=2:
            return b'',sr
        if ch==2:
            out=bytearray()
            for i in range(0,len(raw),4):
                l=int.from_bytes(raw[i:i+2],'little',signed=True)
                r=int.from_bytes(raw[i+2:i+4],'little',signed=True)
                m=(l+r)//2
                out.extend(int(m).to_bytes(2,'little',signed=True))
            raw=bytes(out)
        elif ch!=1:
            return b'',sr
        return raw,sr

    def _wait_device_tts_ack(self,start_ts:float,timeout:float)->bool:
        deadline=time.time()+max(0.8,float(timeout))
        while time.time()<deadline:
            if self.last_voice_event_ts>start_ts:
                kind=self.last_voice_event_kind
                payload=(self.last_voice_event_payload or '').strip().lower()
                if kind=='tts':
                    return True
                if kind=='state' and payload in ('pcm_begin','pcm_end','speaking','idle'):
                    return True
            time.sleep(0.05)
        return False

    def _self_test_speaker(self)->None:
        if not self.ser:
            messagebox.showwarning('提示','请先连接串口后再做喇叭自检。')
            return
        ok=self._tts_device('小医喇叭测试，如果你听到这句话说明设备喇叭播报链路可用。')
        if ok:
            self._status('设备喇叭播报正常')
            self._log('[speaker_test] 设备喇叭播报链路正常')
            return
        self._status('设备喇叭播报未确认，回退本机播报')
        self._log('[speaker_test] 未确认设备喇叭播放，可能原因：固件不支持串口播报协议，或喇叭接线/功放异常。')

    def _self_test_voice(self)->None:
        if not self.ser:
            messagebox.showwarning('提示','请先连接串口后再做语音自检。')
            return
        start=time.time()
        wk=self.var_wake.get().strip() or DEFAULT_WAKE
        self._log(f'[self_test] 开始串口语音链路自检：请先说唤醒词“{wk}”，再说业务指令（如“23床现在重点”）。')
        self._status('语音自检中...')
        self.auto_listen_enabled=True
        self._enforce_local_mode(force_start=True,reason='语音自检')
        def _watch()->None:
            # 若设备刚上电还在 activating，给更长等待时间
            deadline=start+45
            got_listening=False
            while time.time()<deadline:
                if self.last_voice_event_ts>=start:
                    kind=self.last_voice_event_kind
                    payload=(self.last_voice_event_payload or '').strip().lower()
                    if kind in ('wake','stt'):
                        self.q_ui.put(('log',f"[self_test] 通过：捕获到 {kind} -> {self.last_voice_event_payload}"))
                        self.q_ui.put(('status','语音链路正常'))
                        return
                    if kind=='state' and payload in ('listening','speaking'):
                        got_listening=True
                time.sleep(0.2)
            if got_listening:
                self.q_ui.put(('log','[self_test] 结果：设备已进入 listening，但未捕获到 wake/stt（这通常是麦克风链路问题，不是后端问题）。请检查 INMP441 的 LR 是否接地、SD/WS/SCK 是否与固件引脚一致。'))
            else:
                self.q_ui.put(('log','[self_test] 未进入 listening 且未捕获 wake/stt：请先确认固件联网激活完成，再检查串口与固件版本。'))
            self.q_ui.put(('status','语音链路异常（未捕获真实语音事件）'))
        threading.Thread(target=_watch,daemon=True).start()

    def _serial_write_line(self,text:str)->None:
        with self.lock:
            if not self.ser:return
            try:
                line=(text or '').replace('\r','').replace('\n','').strip()
                if not line:
                    return
                now=time.time()
                delta=now-self.last_serial_write_ts
                if delta<0.08:
                    time.sleep(0.08-delta)
                self.ser.write((line+'\n').encode('utf-8',errors='ignore'))
                self.ser.flush()
                self.last_serial_write_ts=time.time()
            except Exception as e:self._log(f'[serial_write_error] {e}')

    def _save_hist(self,row:dict[str,Any])->None:
        with self.histf.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

    def _load_hist(self)->None:
        self.lst.delete(0,tk.END);self.hcache=[]
        if not self.histf.exists():return
        for line in self.histf.read_text(encoding='utf-8').splitlines():
            try:
                r=json.loads(line)
                if isinstance(r,dict):self.hcache.append(r)
            except Exception:continue
        self.hcache=self.hcache[-300:]
        for r in self.hcache:self.lst.insert(tk.END,f"{r.get('time','')} | {r.get('source','')} | {str(r.get('input',''))[:40]}")

    def _append_hist(self,row:dict[str,Any])->None:
        self.hcache.append(row)
        if len(self.hcache)>300:self.hcache=self.hcache[-300:]
        self.lst.insert(tk.END,f"{row.get('time','')} | {row.get('source','')} | {str(row.get('input',''))[:40]}")
        self.lst.see(tk.END)

    def _pick(self,_:Any)->None:
        sel=self.lst.curselection()
        if not sel:return
        i=int(sel[0])
        if i<0 or i>=len(self.hcache):return
        r=self.hcache[i];self.txt_in.delete('1.0',tk.END);self.txt_in.insert('1.0',r.get('input',''));self._log(f"[history_pick] {r.get('time','')} -> 已填入输入框")

    def _uid(self,raw:str)->str:
        u=(raw or '').strip()
        if not u:return 'u_linmeili'
        if u.startswith('u_'):return u
        safe=re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff]','',u) or DEFAULT_USER
        return f'u_{safe}'

    def _ensure_user(self,user_input:str)->str:
        api=self.var_api.get().strip().rstrip('/');uid=self._uid(user_input);name=uid[2:] if uid.startswith('u_') else uid;name=name or DEFAULT_USER
        try:
            r=requests.post(f'{api}/api/auth/register',json={'username':name,'password':'123456','full_name':'林美丽' if name=='linmeili' else name,'role_code':'nurse','phone':None},timeout=10)
            if r.status_code in (200,201):
                b=r.json() if isinstance(r.json(),dict) else {};u=b.get('user') if isinstance(b.get('user'),dict) else {};uid=str(u.get('id') or uid);self.var_user.set(name);return uid
            if r.status_code==409:self.var_user.set(name);return uid
            self._log(f'[bind_warn] register status={r.status_code} body={r.text[:180]}');return uid
        except Exception as e:
            self._log(f'[bind_warn] {e}');return uid

    def _close(self)->None:
        self.stop_w.set();self.stop_s.set();self._save_cfg();self._disconnect();self.destroy()

if __name__=='__main__':
    App().mainloop()








