# Документація проєкту

| Файл | Зміст |
|---|---|
| [project-overview.md](project-overview.md) | Мета, ролі, сценарії, стан реалізації |
| [architecture.md](architecture.md) | Модулі системи й за що кожен відповідає |
| [modules/accounts.md](modules/accounts.md) | Користувачі, ролі, вхід |
| [modules/catalog.md](modules/catalog.md) | Каталог: типи, екземпляри, тарифи |
| [modules/bookings.md](modules/bookings.md) | Бронювання, перевірка перетину, вартість, статуси |
| [migrations/README.md](migrations/README.md) | Інструмент міграцій, команди, правила, перелік міграцій |
| [tooling-and-ai.md](tooling-and-ai.md) | Інструментарій розробки та журнал використання ШІ |

## Правило ведення

Документацію змінюють у тому самому коміті, що й код:

- нова міграція → новий файл у `migrations/` і рядок у переліку `migrations/README.md`;
- нова функція → оновлення відповідного файлу в `modules/`;
- використання ШІ → запис у журналі `tooling-and-ai.md`.
