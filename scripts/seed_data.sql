-- Seed categories
INSERT INTO budget.categories (id, name, parent_id) VALUES
-- Parent Categories (NULL)
(1, '{"en": "Income", "ru": "Доход"}', NULL),
(2, '{"en": "Transfer", "ru": "Перевод"}', NULL),
(3, '{"en": "Food", "ru": "Еда"}', NULL),
(4, '{"en": "Housing", "ru": "Жилье"}', NULL),
(5, '{"en": "Transport", "ru": "Транспорт"}', NULL),
(6, '{"en": "Kids", "ru": "Дети"}', NULL),
(7, '{"en": "Lifestyle", "ru": "Личные расходы"}', NULL),
(8, '{"en": "Financial", "ru": "Финансы"}', NULL),
(9, '{"en": "Pets", "ru": "Питомцы"}', NULL),
(10, '{"en": "Gifts & Charity", "ru": "Подарки и благотворительность"}', NULL),

-- Income (1)
(11, '{"en": "Salary", "ru": "Зарплата"}', 1),
(12, '{"en": "Refunds & Cashback", "ru": "Возвраты и кэшбэк"}', 1),
(13, '{"en": "Other Income", "ru": "Прочие доходы"}', 1),
(14, '{"en": "Allowances & Benefits", "ru": "Пособия и выплаты"}', 1),

-- Transfer (2)
(15, '{"en": "Internal Transfer", "ru": "Перевод между своими счетами"}', 2),
(16, '{"en": "Private Transfers & Payments", "ru": "Переводы и частные платежи"}', 2),

-- Food (3)
(17, '{"en": "Junk Food & Sweets", "ru": "Вредная еда и сладости"}', 3),
(18, '{"en": "Supermarkets & Groceries", "ru": "Продукты и супермаркеты"}', 3),
(19, '{"en": "Restaurants & Delivery", "ru": "Рестораны и доставка"}', 3),

-- Housing (4)
(20, '{"en": "Internet & Mobile", "ru": "Связь и интернет"}', 4),
(21, '{"en": "Rent, Arnona & Vaad Bayit", "ru": "Аренда, Арнона и Ваад байт"}', 4),
(22, '{"en": "Utilities (Metered)", "ru": "Свет, Вода, Газ"}', 4),
(23, '{"en": "Home Maintenance", "ru": "Ремонт и уют"}', 4),
(24, '{"en": "Household & Cleaning", "ru": "Хозтовары и бытовая химия"}', 4),
(25, '{"en": "Electronics & Appliances", "ru": "Техника и электроника"}', 4),

-- Transport (5)
(26, '{"en": "Car & Fuel", "ru": "Авто и бензин"}', 5),
(27, '{"en": "Public Transport & Taxi", "ru": "Общественный транспорт и такси"}', 5),
(28, '{"en": "Car Maintenance & Repairs", "ru": "Сервис и ремонт авто"}', 5),
(29, '{"en": "Car Insurance & Licensing", "ru": "Страховка и налоги на авто"}', 5),

-- Kids (6)
(30, '{"en": "Daycare & Education", "ru": "Садик и учеба"}', 6),
(31, '{"en": "Toys & Clothes", "ru": "Игрушки и одежда"}', 6),

-- Lifestyle (7)
(32, '{"en": "Health & Beauty", "ru": "Здоровье и красота"}', 7),
(33, '{"en": "Entertainment", "ru": "Развлечения"}', 7),
(34, '{"en": "Clothing", "ru": "Одежда и обувь"}', 7),
(35, '{"en": "Subscriptions", "ru": "Подписки"}', 7),
(36, '{"en": "Travel & Vacation", "ru": "Путешествия и отдых"}', 7),
(37, '{"en": "Hobbies & Sport", "ru": "Хобби и спорт"}', 7),
(38, '{"en": "Marketplaces & Online Shopping", "ru": "Маркетплейсы и онлайн-магазины"}', 7),
(39, '{"en": "Education & Courses", "ru": "Обучение и курсы"}', 7),

-- Financial (8)
(40, '{"en": "Loans & Debt", "ru": "Кредиты и долги"}', 8),
(41, '{"en": "Savings & Investments", "ru": "Сбережения и инвестиции"}', 8),
(42, '{"en": "Fees & Taxes", "ru": "Налоги и комиссии"}', 8),
(43, '{"en": "Cash Withdrawal", "ru": "Снятие наличных"}', 8),
(44, '{"en": "Unaccounted Expenses", "ru": "Неучтенные расходы"}', 8)
ON CONFLICT (id) DO UPDATE SET 
    name = EXCLUDED.name,
    parent_id = EXCLUDED.parent_id;

-- Reset sequence
SELECT setval('budget.categories_id_seq', (SELECT max(id) FROM budget.categories));

