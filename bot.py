"""Bridge private WeChat iLink messages to local Codex CLI sessions."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from weixin_ilink import WeixinBot


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CREDS = DATA / "ilink-credentials.json"
SESSIONS = DATA / "sessions.json"
ALLOWED = DATA / "allowed-users.json"
MAX_PENDING = 50
MAX_WORKERS = 3
CODEX_TIMEOUT = 300
INTRO = (
    "你是通过微信接入的本机 Codex 助手。请用简洁的中文回答。"
    "涉及当天信息时使用实时联网搜索，并给出可访问的来源链接。"
    "不要向其他用户透露本机文件、凭据或其他微信联系人的信息。"
)
ACCESS_INSTRUCTION = "此前的只读限制已解除。根据当前用户请求，可以修改文件、运行命令和联网。"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessions: dict[str, str] = read_json(SESSIONS, {})
        self.allowed: list[str] = read_json(ALLOWED, [])

    def is_allowed(self, user_id: str) -> bool:
        with self.lock:
            self.allowed = read_json(ALLOWED, [])
            return user_id in self.allowed

    def allow(self, user_id: str) -> None:
        with self.lock:
            self.allowed = read_json(ALLOWED, [])
            if user_id not in self.allowed:
                self.allowed.append(user_id)
                write_json(ALLOWED, self.allowed)

    def revoke(self, user_id: str) -> None:
        with self.lock:
            self.allowed = read_json(ALLOWED, [])
            if user_id in self.allowed:
                self.allowed.remove(user_id)
                write_json(ALLOWED, self.allowed)

    def session(self, user_id: str) -> str | None:
        with self.lock:
            return self.sessions.get(user_id)

    def set_session(self, user_id: str, thread_id: str) -> None:
        with self.lock:
            self.sessions[user_id] = thread_id
            write_json(SESSIONS, self.sessions)

    def reset_session(self, user_id: str) -> None:
        with self.lock:
            self.sessions.pop(user_id, None)
            write_json(SESSIONS, self.sessions)


class CodexRunner:
    def __init__(self) -> None:
        self.command = os.environ.get("CODEX_COMMAND") or shutil.which("codex.cmd") or shutil.which("codex")
        if not self.command:
            raise RuntimeError("找不到 Codex CLI。先安装 Codex CLI 并运行 codex login。")

    def ask(self, prompt: str, thread_id: str | None) -> tuple[str, str]:
        common = [
            "-c", 'web_search="live"',
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check", "--json",
        ]
        if thread_id:
            command = [self.command, "exec", "resume", *common, thread_id, "-"]
            message = f"{ACCESS_INSTRUCTION}\n\n用户消息：\n{prompt}"
        else:
            command = [self.command, "exec", *common, "--cd", str(ROOT), "-"]
            message = f"{INTRO}\n{ACCESS_INSTRUCTION}\n\n用户消息：\n{prompt}"

        result = subprocess.run(
            command, input=message.encode("utf-8"), capture_output=True,
            cwd=ROOT, timeout=CODEX_TIMEOUT, check=False,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        started_thread = thread_id
        response = ""
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                started_thread = event.get("thread_id") or started_thread
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                response = item.get("text") or response

        if result.returncode != 0:
            logging.error("Codex exited %s: %s", result.returncode, stderr[-2000:])
            raise RuntimeError("Codex 执行失败；请在电脑终端查看日志。")
        if not started_thread or not response:
            logging.error("Incomplete Codex response: %s", stdout[-2000:])
            raise RuntimeError("Codex 没有返回完整回复；请在电脑终端查看日志。")
        return started_thread, response


class MessageQueue:
    def __init__(self, bot: WeixinBot, state: State, codex: CodexRunner) -> None:
        self.bot = bot
        self.state = state
        self.codex = codex
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.lock = threading.Lock()
        self.pending: dict[str, deque] = defaultdict(deque)
        self.running: set[str] = set()
        self.total_pending = 0

    def enqueue(self, message: object) -> bool:
        user_id = message.from_user
        with self.lock:
            if self.total_pending >= MAX_PENDING:
                return False
            self.pending[user_id].append(message)
            self.total_pending += 1
            if user_id not in self.running:
                self.running.add(user_id)
                self.pool.submit(self._drain, user_id)
        return True

    def _drain(self, user_id: str) -> None:
        while True:
            with self.lock:
                if not self.pending[user_id]:
                    self.running.remove(user_id)
                    self.pending.pop(user_id)
                    return
                message = self.pending[user_id].popleft()
                self.total_pending -= 1
            self._handle(message)

    def _handle(self, message: object) -> None:
        try:
            prompt = (message.text or "").strip()
            if prompt == "/reset":
                self.state.reset_session(message.from_user)
                message.reply_text("已开启新会话。")
                return
            thread_id, answer = self.codex.ask(prompt, self.state.session(message.from_user))
            self.state.set_session(message.from_user, thread_id)
            message.reply_text(answer)
        except subprocess.TimeoutExpired:
            logging.exception("Codex timed out for %s", message.from_user)
            self._reply_error(message, "处理超时，请稍后重试。")
        except Exception:
            logging.exception("Failed to handle message from %s", message.from_user)
            self._reply_error(message, "处理失败，请在电脑终端查看日志。")

    @staticmethod
    def _reply_error(message: object, text: str) -> None:
        try:
            message.reply_text(text)
        except Exception:
            logging.exception("Failed to send error reply")

    def close(self) -> None:
        self.pool.shutdown(wait=True)


def serve(state: State) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if not CREDS.exists():
        print("首次登录：请用个人微信扫描终端里的二维码。")
        bot = WeixinBot.from_login(save_to=CREDS)
    else:
        bot = WeixinBot(credentials_file=CREDS)
    owner_id = bot.info.get("userId")
    if owner_id:
        state.allow(owner_id)
    queue = MessageQueue(bot, state, CodexRunner())

    @bot.on_text
    def on_text(message: object) -> None:
        if not state.is_allowed(message.from_user):
            logging.info("Pending authorization: %s", message.from_user)
            message.reply_text(f"尚未授权。请把这个用户 ID 发给管理员：\n{message.from_user}")
            return
        if not (message.text or "").strip():
            return
        if not queue.enqueue(message):
            message.reply_text("当前消息较多，请稍后再发。")

    print(f"微信 Bot 已启动：{bot.account_id}。按 Ctrl+C 退出。")
    try:
        bot.run()
    finally:
        queue.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="个人微信 iLink → 本机 Codex")
    parser.add_argument("action", nargs="?", choices=("serve", "allow", "revoke", "users", "reset", "login"), default="serve")
    parser.add_argument("user_id", nargs="?")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = State()
    if args.action == "serve":
        serve(state)
    elif args.action == "login":
        DATA.mkdir(parents=True, exist_ok=True)
        WeixinBot.from_login(save_to=CREDS)
        print("扫码登录成功。现在运行 python bot.py serve。")
    elif args.action == "users":
        print("\n".join(state.allowed) or "尚无已授权用户")
    elif args.user_id:
        if args.action == "allow":
            state.allow(args.user_id)
            print("已授权：", args.user_id)
        elif args.action == "revoke":
            state.revoke(args.user_id)
            print("已撤销：", args.user_id)
        elif args.action == "reset":
            state.reset_session(args.user_id)
            print("已重置会话：", args.user_id)
    else:
        parser.error(f"{args.action} 需要微信用户 ID")


if __name__ == "__main__":
    main()
