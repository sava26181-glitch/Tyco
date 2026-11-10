# От курьера до магната

Игра в Telegram: начинаешь курьером с рюкзаком и становишься магнатом. Бесконечные дни с событиями, прокачка, транспорт, знакомства с чатами, бизнесы, NFT-подарки с маркетом и фото персонажа на аватарку. Доход приносят покупки за Telegram Stars и реклама Adsgram.

## Запуск
1. В @BotFather: `/newbot`, сохрани токен. Свой ID узнай у @userinfobot.
2. Загрузи эту папку в приватный репозиторий GitHub.
3. На render.com: **New → Blueprint** и выбери репозиторий. Заполни `BOT_TOKEN`, `ADMIN_ID`, `SUPPORT_CONTACT`. `APP_LINK` и `ADSGRAM_BLOCK_ID` пока поставь `-`.
4. Дождись статуса **Live**. В BotFather отправь `/newapp`, укажи адрес сервиса с Render и короткое имя, например `game`.
5. Ссылку `https://t.me/имя_бота/game` впиши в `APP_LINK` на Render и нажми **Save Changes**.
6. Реклама (по желанию): блок Reward на partner.adsgram.ai, Reward URL
   `https://АДРЕС/adsgram/reward?userid=[userId]&secret=ADSGRAM_SECRET`, номер блока впиши в `ADSGRAM_BLOCK_ID`.

Если создаёшь сервис вручную, а не через Blueprint: Build `pip install -r requirements.txt`, Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, плюс переменные `DATABASE_URL` (Internal URL базы Postgres), `WEBHOOK_SECRET` и `ADSGRAM_SECRET` (длинные строки из латиницы и цифр), `PYTHON_VERSION=3.13.1`.

## Что где менять
- Цены, события, бизнесы, подарки, транспорт: `app/game.py`.
- Экраны и рисунки: `static/index.html`.

## Команды бота
`/stats` — статистика для `ADMIN_ID`, `/paysupport`, `/terms`.

## Проверка
`pip install -r requirements-dev.txt` и `pytest -q`.

Деньги, подарки и VIP — внутриигровые предметы, их нельзя вывести или обменять на настоящие деньги. Секреты храни только в Environment на Render.
