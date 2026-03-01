# QA Agent — Рабочие правила

## Контекст системы
- Проверяем работающий сайт: http://127.0.0.1:PORT
- Проверки через curl (не через браузер)
- PM2_HOME=/root/core/.pm2 pm2 list — проверить что процесс online

## Стандартный чеклист для лендинга
```bash
# 1. HTTP статус
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:PORT

# 2. Содержимое страницы
curl -s http://127.0.0.1:PORT | grep -o "<title>.*</title>"

# 3. Наличие ключевых секций
curl -s http://127.0.0.1:PORT | grep -c "form\|button\|hero"

# 4. PM2 статус
PM2_HOME=/root/core/.pm2 pm2 list | grep <name>

# 5. API endpoint (если есть)
curl -s -X POST http://127.0.0.1:PORT/api/endpoint \
  -H "Content-Type: application/json" \
  -d '{"test": true}' | head -100
```

## Критерии PASS/FAIL
- PASS (decision=done): HTTP 200, страница содержит контент, процесс online
- FAIL (decision=blocked): HTTP 4xx/5xx, процесс crashed, страница пустая, форма не отвечает

## Запреты
- НЕ использовать nano, vim, vi
- НЕ запускать npm run build/dev/start
- НЕ модифицировать исходный код — только проверять

## Задача завершена когда
В note: URL проверки, HTTP статус, что нашёл (pass/fail по каждому пункту), итоговый вердикт
