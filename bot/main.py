"""Long polling и команды бота."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, Message, Update, User

from bot.config import Config, load_config
from bot.ollama import (
    OllamaClient,
    OllamaDown,
    OllamaError,
    OllamaModelNotFound,
    OllamaTimeout,
)
from bot.store import Store, default_db_path

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096

HELP = (
    "Пишите текст — он уйдёт в локальную Ollama вместе с историей этого чата.\n"
    "/models — список моделей\n"
    "/model <name> — выбрать модель\n"
    "/status — Ollama, модель, длина истории\n"
    "/reset — очистить историю"
)


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self, allowed: frozenset[int]) -> None:
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        user = _sender(event) or data.get("event_from_user")
        if not isinstance(user, User) or user.id not in self.allowed:
            return None
        return await handler(event, data)


def _sender(event: object) -> User | None:
    user = getattr(event, "from_user", None)
    if isinstance(user, User):
        return user
    if not isinstance(event, Update):
        return None
    for name in (
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "shipping_query",
        "pre_checkout_query",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "business_message",
        "edited_business_message",
    ):
        inner = getattr(event, name, None)
        if inner is None:
            continue
        user = getattr(inner, "from_user", None)
        if isinstance(user, User):
            return user
    return None


def split_text(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    remaining = text.strip()
    if not remaining:
        return []
    parts: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [part for part in parts if part]


def error_text(exc: Exception) -> str:
    if isinstance(exc, OllamaDown):
        return "Ollama не отвечает."
    if isinstance(exc, OllamaTimeout):
        return "Ollama не ответила вовремя."
    if isinstance(exc, OllamaModelNotFound):
        return f"Модель «{exc.model}» не найдена."
    if isinstance(exc, OllamaError):
        logger.warning("ollama: %s", exc)
        return "Ошибка Ollama."
    logger.exception("неожиданная ошибка")
    return "Не получилось обработать сообщение."


async def answer_long(message: Message, text: str) -> None:
    parts = split_text(text)
    if not parts:
        await message.answer("Пустой ответ.")
        return
    for part in parts:
        await message.answer(part)


async def _typing_loop(bot: Bot, chat_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            logger.debug("не удалось отправить typing", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except TimeoutError:
            continue


def _effective_model(store: Store, config: Config, chat_id: int) -> str | None:
    return store.get_model(chat_id) or config.default_model


def setup_dispatcher(
    dp: Dispatcher, *, config: Config, store: Store, ollama: OllamaClient
) -> None:
    dp.update.middleware(AllowlistMiddleware(config.allowed_user_ids))
    locks: dict[int, asyncio.Lock] = {}

    def chat_lock(chat_id: int) -> asyncio.Lock:
        lock = locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[chat_id] = lock
        return lock

    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await message.answer(HELP)

    @dp.message(Command("models"))
    async def cmd_models(message: Message) -> None:
        try:
            names = await ollama.list_models()
        except (OllamaDown, OllamaTimeout, OllamaError) as exc:
            await message.answer(error_text(exc))
            return
        if not names:
            await message.answer("Локальных моделей нет.")
            return
        await answer_long(message, "Модели:\n" + "\n".join(names))

    @dp.message(Command("model"))
    async def cmd_model(message: Message, command: CommandObject) -> None:
        name = (command.args or "").strip()
        if not name or any(ch.isspace() for ch in name):
            await message.answer("Укажите имя: /model <name>")
            return
        try:
            names = await ollama.list_models()
        except (OllamaDown, OllamaTimeout, OllamaError) as exc:
            await message.answer(error_text(exc))
            return
        if name not in names:
            await message.answer(f"Модель «{name}» не найдена.")
            return
        store.set_model(message.chat.id, name)
        await message.answer(f"Модель для этого чата: {name}")

    @dp.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        up = await ollama.health()
        model = _effective_model(store, config, message.chat.id) or "не выбрана"
        length = store.history_length(message.chat.id)
        state = "работает" if up else "не отвечает"
        await message.answer(
            f"Ollama: {state}\nМодель: {model}\nИстория: {length}"
        )

    @dp.message(Command("reset"))
    async def cmd_reset(message: Message) -> None:
        async with chat_lock(message.chat.id):
            store.clear_history(message.chat.id)
        await message.answer("История очищена.")

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return
        model = _effective_model(store, config, message.chat.id)
        if not model:
            await message.answer("Модель не выбрана. Список: /models")
            return

        async with chat_lock(message.chat.id):
            messages = store.history(message.chat.id)
            messages.append({"role": "user", "content": text})
            stop = asyncio.Event()
            typing = asyncio.create_task(
                _typing_loop(message.bot, message.chat.id, stop)
            )
            try:
                reply = await ollama.chat(model, messages)
            except (OllamaDown, OllamaTimeout, OllamaModelNotFound, OllamaError) as exc:
                await message.answer(error_text(exc))
                return
            except Exception as exc:
                await message.answer(error_text(exc))
                return
            finally:
                stop.set()
                typing.cancel()
                try:
                    await typing
                except asyncio.CancelledError:
                    pass
            store.append_exchange(message.chat.id, text, reply)
        await answer_long(message, reply)


async def run(config: Config) -> None:
    if not config.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS пуст: бот никому не отвечает")
    store = Store(default_db_path())
    ollama = OllamaClient(config.ollama_base_url)
    bot = Bot(token=config.token)
    dp = Dispatcher()
    setup_dispatcher(dp, config=config, store=store, ollama=ollama)
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="models", description="Список локальных моделей"),
                BotCommand(command="model", description="Выбрать модель для чата"),
                BotCommand(command="status", description="Ollama, модель, история"),
                BotCommand(command="reset", description="Очистить историю чата"),
            ]
        )
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await ollama.aclose()
        store.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
