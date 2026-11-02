# b-cane2

Личный Telegram-бот к локальной Ollama. Один процесс, long polling. Ollama должна уже слушать `http://127.0.0.1:11434`.

Нужен Python 3.11–3.13. На 3.15 aiogram сейчас не ставится: у pydantic нет готового колеса.

## Запуск

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

В `.env` впишите токен от BotFather и свой Telegram user id (его присылает `@userinfobot`). Файл `.env` в git не попадает.

```bash
.venv/bin/python -m bot.main
```

Логи идут в этот терминал. Окно закрыли — процесс умер.

## Пример .env

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_USER_IDS=
OLLAMA_BASE_URL=http://127.0.0.1:11434
DEFAULT_MODEL=qwen2.5:14b
```

`ALLOWED_USER_IDS` — целые id через запятую. Чужие апдейты бот молча игнорирует. Пустой список значит, что бот не отвечает никому.

`OLLAMA_BASE_URL` можно не задавать: по умолчанию `http://127.0.0.1:11434`.

`DEFAULT_MODEL` — модель, пока для чата не выбрана своя. Имя должно совпадать со строкой из `/models`. Пустое значение значит, что сначала нужна команда `/model`.

## Команды

Обычный текст уходит в `/api/chat` вместе с историей этого чата и выбранной моделью.

- `/models` — локальные модели
- `/model <name>` — модель для этого чата; неизвестное имя отклоняется
- `/status` — жива ли Ollama, текущая модель, длина истории
- `/reset` — очистить историю этого чата

История и выбранная модель лежат в `data/bot.sqlite` и переживают перезапуск.
