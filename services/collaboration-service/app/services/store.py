from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.collab import (
    AccountOut,
    DirectSessionDetailOut,
    DirectSessionOut,
    MessageOut,
    ThreadHistoryItem,
    ThreadOut,
)


DEFAULT_ACCOUNTS: dict[str, dict[str, Any]] = {
    "u_nurse_01": {
        "id": "u_nurse_01",
        "account": "nurse01",
        "full_name": "张护士",
        "role_code": "nurse",
        "department": "心内科病区",
        "title": "责任护士",
        "status": "active",
    },
    "u_doctor_01": {
        "id": "u_doctor_01",
        "account": "doctor01",
        "full_name": "李医生",
        "role_code": "attending_doctor",
        "department": "心内科",
        "title": "主治医师",
        "status": "active",
    },
    "u_resident_01": {
        "id": "u_resident_01",
        "account": "resident01",
        "full_name": "王住院",
        "role_code": "resident_doctor",
        "department": "心内科",
        "title": "住院医师",
        "status": "active",
    },
    "u_charge_01": {
        "id": "u_charge_01",
        "account": "charge01",
        "full_name": "赵护士长",
        "role_code": "charge_nurse",
        "department": "心内科病区",
        "title": "护士长",
        "status": "active",
    },
    "u_pharm_01": {
        "id": "u_pharm_01",
        "account": "pharm01",
        "full_name": "陈药师",
        "role_code": "pharmacist",
        "department": "药学部",
        "title": "临床药师",
        "status": "active",
    },
}


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


class CollaborationStore:
    def __init__(self) -> None:
        self._threads: list[ThreadOut] = []
        self._messages: list[MessageOut] = []
        self._accounts: dict[str, AccountOut] = {}
        self._contacts: dict[str, set[str]] = {}
        self._direct_sessions: list[dict[str, Any]] = []
        self._direct_messages: list[MessageOut] = []
        self._data_file = Path(__file__).resolve().parents[2] / "data" / "collaboration_store.json"
        self._load()
        self._seed_defaults()

    # ====== 旧版病例线程接口（兼容保留）======
    def create_thread(
        self,
        *,
        patient_id: str | None,
        encounter_id: str | None,
        thread_type: str,
        title: str,
        created_by: str | None,
    ) -> ThreadOut:
        now = datetime.now(timezone.utc)
        thread = ThreadOut(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            encounter_id=encounter_id,
            thread_type=thread_type,
            title=title,
            created_by=created_by,
            status="open",
            created_at=now,
            updated_at=now,
        )
        self._threads.append(thread)
        self._save()
        return thread

    def add_message(
        self,
        *,
        thread_id: str,
        sender_id: str | None,
        message_type: str,
        content: str,
        attachment_refs: list[str],
        ai_generated: bool,
    ) -> MessageOut:
        message = MessageOut(
            id=str(uuid.uuid4()),
            thread_id=thread_id,
            sender_id=sender_id,
            message_type=message_type,
            content=content,
            attachment_refs=attachment_refs,
            ai_generated=ai_generated,
            created_at=datetime.now(timezone.utc),
        )
        self._messages.append(message)
        thread = self.get_thread(thread_id)
        if thread:
            thread.updated_at = datetime.now(timezone.utc)
        self._save()
        return message

    def get_thread(self, thread_id: str) -> ThreadOut | None:
        for item in self._threads:
            if item.id == thread_id:
                return item
        return None

    def list_messages(self, thread_id: str) -> list[MessageOut]:
        return [item for item in self._messages if item.thread_id == thread_id]

    def close_thread(self, thread_id: str) -> ThreadOut | None:
        thread = self.get_thread(thread_id)
        if thread is None:
            return None
        thread.status = "closed"
        thread.updated_at = datetime.now(timezone.utc)
        self._save()
        return thread

    def list_thread_history(self, *, patient_id: str | None = None, limit: int = 50) -> list[ThreadHistoryItem]:
        threads = list(reversed(self._threads))
        if patient_id:
            threads = [item for item in threads if item.patient_id == patient_id]

        message_count_map: dict[str, int] = {}
        latest_message_map: dict[str, MessageOut] = {}
        for message in self._messages:
            message_count_map[message.thread_id] = message_count_map.get(message.thread_id, 0) + 1
            latest_message_map[message.thread_id] = message

        result: list[ThreadHistoryItem] = []
        for thread in threads:
            result.append(
                ThreadHistoryItem(
                    thread=thread,
                    latest_message=latest_message_map.get(thread.id),
                    message_count=message_count_map.get(thread.id, 0),
                )
            )
        return result[:limit]

    # ====== 新版好友/会话 ======
    def search_accounts(self, *, query: str = "", exclude_user_id: str | None = None) -> list[AccountOut]:
        q = (query or "").strip().lower()
        results: list[AccountOut] = []
        for account in self._accounts.values():
            if exclude_user_id and account.id == exclude_user_id:
                continue
            if str(account.status or "active") != "active":
                continue
            if not q:
                results.append(account)
                continue
            joined = (
                f"{account.account} {account.full_name} {account.role_code} "
                f"{account.department or ''} {account.title or ''} {account.phone or ''} {account.email or ''}"
            ).lower()
            if q in joined:
                results.append(account)
        return sorted(results, key=lambda x: (x.role_code, x.full_name))[:50]

    def list_accounts_admin(self, *, query: str = "", status_filter: str | None = None) -> list[AccountOut]:
        q = (query or "").strip().lower()
        status_value = (status_filter or "").strip().lower()
        rows: list[AccountOut] = []
        for account in self._accounts.values():
            if status_value and str(account.status or "").lower() != status_value:
                continue
            if q:
                joined = (
                    f"{account.id} {account.account} {account.full_name} {account.role_code} "
                    f"{account.department or ''} {account.title or ''} {account.phone or ''} {account.email or ''}"
                ).lower()
                if q not in joined:
                    continue
            rows.append(account)
        return sorted(rows, key=lambda item: (item.role_code, item.full_name, item.account))

    def upsert_account(
        self,
        *,
        account_id: str | None,
        account: str,
        full_name: str,
        role_code: str,
        department: str | None = None,
        title: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        status: str = "active",
    ) -> AccountOut:
        account_name = (account or "").strip()
        if not account_name:
            raise ValueError("account_required")

        target_id = (account_id or "").strip()
        existing: AccountOut | None = None
        if target_id and target_id in self._accounts:
            existing = self._accounts[target_id]
        if existing is None:
            for item in self._accounts.values():
                if item.account.lower() == account_name.lower():
                    existing = item
                    break

        record = AccountOut(
            id=existing.id if existing else (target_id or f"u_{account_name}"),
            account=account_name,
            full_name=full_name,
            role_code=role_code,
            department=department,
            title=title,
            phone=phone,
            email=email,
            status=status or "active",
        )
        self._accounts[record.id] = record
        self._contacts.setdefault(record.id, set())
        self._save()
        return record

    def list_contacts(self, user_id: str) -> list[AccountOut]:
        contact_ids = self._contacts.get(user_id, set())
        contacts = [self._accounts[cid] for cid in contact_ids if cid in self._accounts]
        return sorted(contacts, key=lambda x: x.full_name)

    def add_contact(self, *, user_id: str, account: str) -> AccountOut:
        account = (account or "").strip()
        if not account:
            raise ValueError("account_required")

        target = self._find_or_create_account_by_account(account)
        self._contacts.setdefault(user_id, set()).add(target.id)
        self._contacts.setdefault(target.id, set()).add(user_id)
        self._save()
        return target

    def open_direct_session(
        self,
        *,
        user_id: str,
        contact_user_id: str,
        patient_id: str | None = None,
    ) -> DirectSessionOut:
        if contact_user_id not in self._accounts:
            raise ValueError("contact_not_found")
        if user_id not in self._accounts:
            self._accounts[user_id] = AccountOut(
                id=user_id,
                account=user_id.replace("u_", ""),
                full_name=user_id,
                role_code="nurse",
                department="未知科室",
                title=None,
            )
        self._contacts.setdefault(user_id, set()).add(contact_user_id)
        self._contacts.setdefault(contact_user_id, set()).add(user_id)

        for session in self._direct_sessions:
            same_pair = {session["user_id"], session["contact_user_id"]} == {user_id, contact_user_id}
            if same_pair and session.get("status") == "open":
                if patient_id and not session.get("patient_id"):
                    session["patient_id"] = patient_id
                session["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return self._build_direct_session_out(session, owner_user_id=user_id)

        now = datetime.now(timezone.utc).isoformat()
        session = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "contact_user_id": contact_user_id,
            "patient_id": patient_id,
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        self._direct_sessions.append(session)
        self._save()
        return self._build_direct_session_out(session, owner_user_id=user_id)

    def list_direct_sessions(self, *, user_id: str, limit: int = 100) -> list[DirectSessionOut]:
        selected = []
        for session in self._direct_sessions:
            if session.get("status") != "open":
                continue
            if user_id not in {session.get("user_id"), session.get("contact_user_id")}:
                continue
            selected.append(self._build_direct_session_out(session, owner_user_id=user_id))
        selected.sort(key=lambda x: x.updated_at, reverse=True)
        return selected[:limit]

    def get_direct_session_detail(self, session_id: str, owner_user_id: str) -> DirectSessionDetailOut | None:
        raw = self._find_direct_session(session_id)
        if not raw:
            return None
        if owner_user_id not in {raw.get("user_id"), raw.get("contact_user_id")}:
            return None
        messages = [item for item in self._direct_messages if item.thread_id == session_id]
        return DirectSessionDetailOut(
            session=self._build_direct_session_out(raw, owner_user_id=owner_user_id),
            messages=messages,
        )

    def send_direct_message(
        self,
        *,
        session_id: str,
        sender_id: str,
        content: str,
        message_type: str = "text",
        attachment_refs: list[str] | None = None,
    ) -> MessageOut:
        raw = self._find_direct_session(session_id)
        if raw is None:
            raise ValueError("session_not_found")
        if sender_id not in {raw.get("user_id"), raw.get("contact_user_id"), "ai-assistant"}:
            raise ValueError("permission_denied")

        msg = MessageOut(
            id=str(uuid.uuid4()),
            thread_id=session_id,
            sender_id=sender_id,
            message_type=message_type,
            content=content,
            attachment_refs=attachment_refs or [],
            ai_generated=sender_id == "ai-assistant",
            created_at=datetime.now(timezone.utc),
        )
        self._direct_messages.append(msg)
        raw["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        return msg

    # ====== 内部 ======
    def _seed_defaults(self) -> None:
        changed = False
        for uid, row in DEFAULT_ACCOUNTS.items():
            if uid not in self._accounts:
                self._accounts[uid] = AccountOut.model_validate(row)
                changed = True
        for uid in self._accounts:
            self._contacts.setdefault(uid, set())

        for cid in ("u_doctor_01", "u_resident_01", "u_charge_01"):
            if cid in self._accounts and cid not in self._contacts["u_nurse_01"]:
                self._contacts["u_nurse_01"].add(cid)
                self._contacts[cid].add("u_nurse_01")
                changed = True

        if changed:
            self._save()

    def _find_or_create_account_by_account(self, account: str) -> AccountOut:
        account_lower = account.lower()
        for item in self._accounts.values():
            if item.account.lower() == account_lower:
                return item
        user_id = f"u_{account}"
        new_account = AccountOut(
            id=user_id,
            account=account,
            full_name=f"{account}用户",
            role_code="nurse",
            department="未知科室",
            title=None,
            phone=None,
            email=None,
            status="active",
        )
        self._accounts[user_id] = new_account
        return new_account

    def _find_direct_session(self, session_id: str) -> dict[str, Any] | None:
        for session in self._direct_sessions:
            if session.get("id") == session_id:
                return session
        return None

    def _build_direct_session_out(self, session: dict[str, Any], *, owner_user_id: str) -> DirectSessionOut:
        contact_id = session.get("contact_user_id") if session.get("user_id") == owner_user_id else session.get("user_id")
        latest = None
        for item in reversed(self._direct_messages):
            if item.thread_id == session.get("id"):
                latest = item
                break

        return DirectSessionOut(
            id=str(session.get("id")),
            user_id=owner_user_id,
            contact_user_id=str(contact_id),
            patient_id=session.get("patient_id"),
            status=str(session.get("status") or "open"),
            created_at=_parse_dt(session.get("created_at") or datetime.now(timezone.utc).isoformat()),
            updated_at=_parse_dt(session.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            latest_message=latest,
            unread_count=0,
            contact=self._accounts.get(str(contact_id)),
        )

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            payload = json.loads(self._data_file.read_text(encoding="utf-8"))
            self._threads = [ThreadOut.model_validate(item) for item in payload.get("threads", []) if isinstance(item, dict)]
            self._messages = [MessageOut.model_validate(item) for item in payload.get("messages", []) if isinstance(item, dict)]
            self._accounts = {
                item["id"]: AccountOut.model_validate(item)
                for item in payload.get("accounts", [])
                if isinstance(item, dict) and item.get("id")
            }
            self._contacts = {
                user_id: set(values)
                for user_id, values in payload.get("contacts", {}).items()
                if isinstance(user_id, str) and isinstance(values, list)
            }
            self._direct_sessions = [item for item in payload.get("direct_sessions", []) if isinstance(item, dict)]
            self._direct_messages = [
                MessageOut.model_validate(item)
                for item in payload.get("direct_messages", [])
                if isinstance(item, dict)
            ]
        except Exception:
            self._threads = []
            self._messages = []
            self._accounts = {}
            self._contacts = {}
            self._direct_sessions = []
            self._direct_messages = []

    def _save(self) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "threads": [item.model_dump(mode="json") for item in self._threads[-1000:]],
            "messages": [item.model_dump(mode="json") for item in self._messages[-5000:]],
            "accounts": [item.model_dump(mode="json") for item in self._accounts.values()],
            "contacts": {uid: sorted(list(values)) for uid, values in self._contacts.items()},
            "direct_sessions": self._direct_sessions[-2000:],
            "direct_messages": [item.model_dump(mode="json") for item in self._direct_messages[-10000:]],
        }
        self._data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


collaboration_store = CollaborationStore()
