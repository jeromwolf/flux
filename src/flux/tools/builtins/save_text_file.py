import os
from pathlib import Path

SCHEMA = {
    "name": "save_text_file",
    "description": "텍스트 문자열을 파일에 저장합니다. 파이썬 코드 등 긴 문자열도 저장할 수 있습니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "저장할 파일 경로"},
            "content": {"type": "string", "description": "파일에 저장할 문자열 내용"},
            "base_dir": {
                "type": "string",
                "description": "워크스페이스 기준 디렉토리 (기본값: 현재 디렉토리)",
            },
        },
        "required": ["path", "content"],
    },
}

# Generic protected files — .env and .gitignore must never be overwritten by agents
PROTECTED_FILES = {".env", ".env.local", ".env.production", ".env.development", ".gitignore"}
MAX_CONTENT_SIZE = 1024 * 1024  # 1MB


def main(path, content, base_dir=None):
    try:
        workspace = Path(base_dir).resolve() if base_dir else Path(".").resolve()
        resolved = Path(path).resolve()

        # 콘텐츠 크기 제한
        if len(content) > MAX_CONTENT_SIZE:
            return "Error: 파일 크기가 1MB를 초과합니다."

        # 심볼릭 링크 차단
        if Path(path).is_symlink():
            return "Error: 심볼릭 링크는 허용되지 않습니다."

        # 워크스페이스 외부 접근 차단
        if not resolved == workspace and not str(resolved).startswith(str(workspace) + os.sep):
            return "Error: 현재 디렉토리 범위 밖에는 저장할 수 없습니다."

        # 보호 파일 체크
        if resolved.name.lower() in PROTECTED_FILES:
            return f"Error: 보호된 파일입니다: {resolved.name}"

        resolved.parent.mkdir(parents=True, exist_ok=True)
        # O_NOFOLLOW: 심볼릭 링크 추종 방지 (TOCTOU 방지)
        try:
            fd = os.open(str(resolved), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'w') as f:
                f.write(content)
        except OSError as e:
            if e.errno == 40:  # ELOOP - symlink detected
                return "Error: 심볼릭 링크는 허용되지 않습니다."
            raise
        return f"저장 완료: {path}"
    except Exception:
        return "Error: 파일 저장 실패"


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 2:
        print(main(sys.argv[1], sys.argv[2]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
