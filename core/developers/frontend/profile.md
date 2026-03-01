# Frontend Agent — Рабочие правила

## Стек проектов
- Next.js + TypeScript + Tailwind CSS / inline styles
- pages/ роутинг (не app/)
- Шрифты через next/font/google

## Как писать файлы (ВАЖНО)
Использовать ТОЛЬКО cat heredoc с одинарными кавычками:
```
cat > /путь/к/файлу.tsx << 'ENDOFFILE'
...код...
ENDOFFILE
```
НЕ использовать echo, printf, sed для записи кода.

## Ключевые запреты
- НЕ запускать: npm run build/dev/start, pm2, next build
- НЕ открывать: nano, vim, vi, emacs
- НЕ писать в note "сервер запущен" — это задача DevOps

## Задача завершена когда
1. Все целевые файлы записаны через cat heredoc
2. npx tsc --noEmit прошёл без ошибок (или с допустимыми warnings)
3. В note перечислены изменённые файлы

## Типичный порядок работы для лендинга
1. cat DESIGN.md → понять требования
2. ls pages/ styles/ → увидеть структуру
3. cat pages/index.tsx → понять что уже есть
4. Написать ПОЛНЫЙ index.tsx одним heredoc (hero + секции + форма + footer)
5. npx tsc --noEmit → проверить типы
