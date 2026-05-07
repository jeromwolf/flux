"""
schedule_task - AI가 예약 작업을 관리하는 도구

리마인더 설정, 예약 조회, 삭제를 수행합니다.
스케줄은 JSON 파일로 저장되며, 실제 실행은 별도의 scheduler 모듈이 담당합니다.
"""

import json
import os
import uuid
from datetime import datetime

SCHEMA = {
    "name": "schedule_task",
    "description": "예약 작업을 관리합니다. 리마인더 설정, 예약 조회, 삭제 등이 가능합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업: add(추가), list(목록), remove(삭제), history(이력)",
                "enum": ["add", "list", "remove", "history"],
            },
            "schedule_type": {
                "type": "string",
                "description": "once(일회성) 또는 recurring(반복)",
                "enum": ["once", "recurring"],
            },
            "datetime_or_cron": {
                "type": "string",
                "description": "일회성: 'YYYY-MM-DD HH:MM' 형식, 반복: cron 표현식 (예: '30 9 * * 1-5')",
            },
            "content": {
                "type": "string",
                "description": "리마인더 메시지 또는 작업 내용",
            },
            "description": {
                "type": "string",
                "description": "이 예약에 대한 설명",
            },
            "schedule_id": {
                "type": "string",
                "description": "삭제 시 사용할 스케줄 ID",
            },
            "data_dir": {
                "type": "string",
                "description": "스케줄 파일을 저장할 디렉토리 (기본값: 'schedules')",
            },
        },
        "required": ["action"],
    },
}

# ---- 파일 경로 헬퍼 ----

def _get_schedules_file(data_dir=None):
    base = data_dir if data_dir else "schedules"
    return os.path.join(base, "schedules.json")


def _get_history_file(data_dir=None):
    base = data_dir if data_dir else "schedules"
    return os.path.join(base, "history.json")


def _ensure_dir(filepath):
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)


# ---- 저장소 I/O ----

def _load_json(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_json(filepath, data):
    _ensure_dir(filepath)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---- cron / datetime 검증 ----

def _validate_once(datetime_str):
    """'YYYY-MM-DD HH:MM' 형식 검증. 유효하면 None, 오류면 오류 문자열 반환."""
    try:
        dt = datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M")
        if dt < datetime.now():
            return "Error: 이미 지난 시간입니다."
        return None
    except ValueError:
        return "Error: 날짜 형식이 올바르지 않습니다. 'YYYY-MM-DD HH:MM' 형식을 사용하세요."


def _validate_cron(cron_str):
    """cron 표현식 기본 형식 검증 (5개 필드)."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        return "Error: cron 표현식은 5개 필드여야 합니다 (예: '30 9 * * 1-5')."
    return None


# ---- 포맷 헬퍼 ----

def _format_entry(entry):
    """스케줄 항목을 문자열로 포맷"""
    status = "ON" if entry.get("enabled", True) else "OFF"
    stype = entry.get("type", "?")
    desc = entry.get("description", "")
    cron = entry.get("cron", "")
    next_run = entry.get("next_run", "")
    task = entry.get("task", {})
    content = task.get("content", "")
    sid = entry.get("id", "?")

    lines = []
    lines.append(f"[{status}] {desc}" if desc else f"[{status}] (설명 없음)")
    lines.append(f"  ID: {sid}")
    lines.append(f"  유형: {stype}")
    if cron:
        lines.append(f"  cron: {cron}")
    if next_run:
        lines.append(f"  다음 실행: {next_run}")
    if content:
        lines.append(f"  내용: {content}")

    return "\n".join(lines)


# ---- 액션 핸들러 ----

def _handle_add(schedules_file, schedule_type, datetime_or_cron, content, description):
    """예약 추가 처리"""
    if not schedule_type:
        return "Error: schedule_type이 필요합니다 (once 또는 recurring)"
    if not datetime_or_cron:
        return "Error: datetime_or_cron이 필요합니다"
    if not content:
        return "Error: content가 필요합니다"

    # 형식 검증
    if schedule_type == "once":
        err = _validate_once(datetime_or_cron)
        if err:
            return err
        next_run = datetime_or_cron.strip()
        cron = ""
    elif schedule_type == "recurring":
        err = _validate_cron(datetime_or_cron)
        if err:
            return err
        cron = datetime_or_cron.strip()
        next_run = ""
    else:
        return f"Error: 알 수 없는 schedule_type: {schedule_type}"

    task = {
        "action": "remind",
        "content": content,
        "tool_name": None,
        "tool_args": None,
    }

    entry = {
        "id": str(uuid.uuid4()),
        "type": schedule_type,
        "cron": cron,
        "next_run": next_run,
        "task": task,
        "description": description or "",
        "enabled": True,
        "created_at": datetime.now().isoformat(),
    }

    schedules = _load_json(schedules_file)
    schedules.append(entry)
    _save_json(schedules_file, schedules)

    return f"예약이 추가되었습니다.\n\n{_format_entry(entry)}"


def _handle_list(schedules_file):
    """예약 목록 처리"""
    schedules = _load_json(schedules_file)
    if not schedules:
        return "예약된 작업이 없습니다."

    enabled = [s for s in schedules if s.get("enabled", True)]
    disabled = [s for s in schedules if not s.get("enabled", True)]

    lines = [f"예약 작업 ({len(enabled)}개 활성, {len(disabled)}개 비활성):", ""]
    for entry in enabled:
        lines.append(_format_entry(entry))
        lines.append("")
    if disabled:
        lines.append(f"--- 비활성 ({len(disabled)}개) ---")
        for entry in disabled:
            lines.append(_format_entry(entry))
            lines.append("")

    return "\n".join(lines)


def _handle_remove(schedules_file, schedule_id):
    """예약 삭제 처리"""
    if not schedule_id:
        return "Error: schedule_id가 필요합니다"

    schedules = _load_json(schedules_file)
    target = None
    for s in schedules:
        if s["id"] == schedule_id or s["id"].startswith(schedule_id):
            target = s
            break

    if not target:
        return f"해당 ID를 찾을 수 없습니다: {schedule_id}"

    schedules = [s for s in schedules if s["id"] != target["id"]]
    _save_json(schedules_file, schedules)
    return f"예약이 삭제되었습니다: {target['id']}"


def _handle_history(history_file):
    """실행 이력 처리"""
    history = _load_json(history_file)
    if not history:
        return "실행 이력이 없습니다."

    # 최신 20건만 표시
    recent = history[-20:] if len(history) > 20 else history
    recent = list(reversed(recent))

    lines = [f"최근 실행 이력 ({len(recent)}건):", ""]
    for h in recent:
        executed = h.get("executed_at", "?")
        sid = h.get("schedule_id", "?")[:8]
        result = h.get("result", "")
        lines.append(f"  [{executed}] {sid}... => {result}")

    return "\n".join(lines)


# ---- 메인 진입점 ----

def main(action, schedule_type=None, datetime_or_cron=None,
         content=None, description=None, schedule_id=None, data_dir=None):
    """예약 작업 관리 도구 진입점"""
    try:
        schedules_file = _get_schedules_file(data_dir)
        history_file = _get_history_file(data_dir)

        if action == "add":
            return _handle_add(schedules_file, schedule_type, datetime_or_cron, content, description)
        elif action == "list":
            return _handle_list(schedules_file)
        elif action == "remove":
            return _handle_remove(schedules_file, schedule_id)
        elif action == "history":
            return _handle_history(history_file)
        else:
            return f"Error: 알 수 없는 action: {action} (add, list, remove, history 중 선택)"
    except Exception as e:
        return f"Error: 작업 처리 실패 - {e}"


if __name__ == "__main__":
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
