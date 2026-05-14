# T1. CI на GitHub Actions

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — без CI любая регрессия проедет в master незаметно.
> **Зависимости**: нет.

**Цель**: на каждый push в любую ветку и на каждый PR запускать `pytest -v` в GitHub Actions.
Текущее состояние: тестов > 100 (`pytest --collect-only -q`), но CI отсутствует.

**Файлы (новые)**:

| Файл                       | Назначение                                  |
|----------------------------|---------------------------------------------|
| `.github/workflows/test.yml` | Описание CI-пайплайна                     |
| `requirements-dev.txt`     | Pinned dev-зависимости для тестов           |

**Пошагово**:

1. Создай `requirements-dev.txt` (если есть `pyproject.toml` с `[project.optional-dependencies]`
   — добавь туда `test = [...]` вместо отдельного файла, но не смешивай оба варианта):
   ```
   pytest>=8,<9
   pytest-asyncio>=0.23,<1
   aioresponses>=0.7,<1
   ```
2. Создай `.github/workflows/test.yml`:
   ```yaml
   name: tests
   on:
     push:
     pull_request:
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - name: Set up Python
           uses: actions/setup-python@v5
           with:
             python-version: "3.11"
             cache: pip
         - name: Install deps
           run: |
             python -m pip install --upgrade pip
             pip install -r requirements.txt -r requirements-dev.txt
         - name: Run tests
           run: pytest -v --tb=short
   ```
3. Проверь локально перед коммитом:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   pytest -v
   ```
   Все тесты должны быть зелёные.
4. Запушь и убедись в Actions UI, что джоба `tests` зелёная.

**Edge cases**:

- Если `pytest-asyncio` ругается на mode → добавь в `pyproject.toml` (или `pytest.ini`):
  ```ini
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  ```
- Если есть тесты, требующие `BINANCE_API_KEY` и т.п. → они должны мокаться или скипаться
  без env. Если падают — это сигнал, что тест не изолирован, фиксь тест, а не CI.

**Готовность**:

- Бэйдж `tests passing` в Actions для push в `master`.
- Зелёная джоба для open PR.
