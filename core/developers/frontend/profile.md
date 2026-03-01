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

## Генерация изображений через FAL.AI
Если в DESIGN.md есть секция `## Изображения` или нужны фоны/картинки:
```bash
# Генерация: /root/core/scripts/fal_image.sh "промпт" /путь/к/файлу.jpg [размер]
# Размеры: landscape_4_3 | landscape_16_9 | square | portrait_4_3
/root/core/scripts/fal_image.sh "dark gaming neon hero background, cyberpunk purple blue" /root/projects/<name>/public/hero-bg.jpg landscape_16_9

# Использование в JSX:
# <img src="/hero-bg.jpg" style={{position:"absolute", inset:0, width:"100%", height:"100%", objectFit:"cover", opacity:0.4}} />
# Или как CSS background:
# backgroundImage: "url('/hero-bg.jpg')"
```
Всегда добавляй overlay (полупрозрачный div поверх) чтобы текст читался.

## Ключевые запреты
- НЕ запускать: npm run build/dev/start, pm2, next build
- НЕ открывать: nano, vim, vi, emacs
- НЕ писать в note "сервер запущен" — это задача DevOps

## Задача завершена когда
1. Все целевые файлы записаны через cat heredoc
2. npx tsc --noEmit прошёл без ошибок (или с допустимыми warnings)
3. В note перечислены изменённые файлы + какие изображения сгенерированы

## КРИТИЧНО: НЕ говори decision=done если есть TypeScript ошибки
Если npx tsc --noEmit выдаёт ошибки — ИСПРАВЬ их сначала. Только 0 ошибок = можно сказать done.
Допустимы ТОЛЬКО warnings типа "Cannot find module 'ws'" (внешние пакеты без типов).
Ошибки типа "Type X is not assignable to Y", "Property X does not exist" — нужно исправить.

## Типичный порядок работы для лендинга
1. cat DESIGN.md → понять требования и цветовую схему
2. ls pages/ styles/ public/ → увидеть структуру
3. cat pages/index.tsx → понять что уже есть
4. Если нужны изображения — сначала генерируй их через fal_image.sh
5. Написать ПОЛНЫЙ index.tsx одним heredoc
6. npx tsc --noEmit → проверить типы
