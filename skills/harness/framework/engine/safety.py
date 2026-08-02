import re
from typing import Optional


class SafetyFilter:
    """프레임워크 레벨 위험 명령 필터."""

    DANGEROUS_PATTERNS = [
        # 절대경로 재귀 삭제 (rm -rf /, rm -rf /etc 등)
        (re.compile(r"\brm\b.*\s-[rRfFiI]*[rR][rRfFiI]*\s+/"), "absolute path recursive deletion (rm -rf /)"),
        # path traversal을 포함한 rm (rm -rf ../)
        (re.compile(r"\brm\b.*\s\.\./"), "path traversal deletion (rm .../)"),
        # phases/ 삭제 시도
        (re.compile(r"\brm\b.*\bphases/"), "phases SSOT deletion (rm phases/)"),
        # git 위험 작업
        (re.compile(r"git\s+push\s+--force"), "force push (git push --force)"),
        (re.compile(r"git\s+reset\s+--hard"), "hard reset (git reset --hard)"),
        # 원격 코드 실행 (curl/wget 파이프)
        (re.compile(r"\bcurl\b.*\|\s*(ba?sh|sh|zsh|fish|python3?|node|ruby|perl)\b"), "remote code execution (curl | shell)"),
        (re.compile(r"\bwget\b.*-O\s*-\b"), "piped download (wget -O -)"),
        # 시스템 파일 직접 덮어쓰기
        (re.compile(r">\s*/etc/"), "system file overwrite (> /etc/)"),
        # DB
        (re.compile(r"DROP\s+TABLE", re.IGNORECASE), "SQL table drop (DROP TABLE)"),
        # 저수준 디스크 작업
        (re.compile(r"\bmkfs\."), "filesystem formatting (mkfs)"),
        (re.compile(r"\bdd\s+if="), "raw disk write (dd if=)"),
    ]

    @classmethod
    def check_command(cls, command: list[str]) -> Optional[str]:
        cmd_str = " ".join(command)
        for pattern, reason in cls.DANGEROUS_PATTERNS:
            if pattern.search(cmd_str):
                return f"BLOCKED: 위험한 명령어가 감지되었습니다 — {reason}. 명령: {cmd_str}"
        return None
