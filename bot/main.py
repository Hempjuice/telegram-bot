import config
import aiohttp
import base64
import os

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import BotCommand, ContentTypes, Message, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

# Инициализируем бота
bot = Bot(token=config.TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher(bot, storage=MemoryStorage())

# Инициализируем настройки подключения
auth = aiohttp.BasicAuth(login=config.LOGIN, password=config.PASSWORD, encoding='UTF8')


class UserInput(StatesGroup):
    searchText = State()
    orderNumber = State()
    userEmail = State()
    verificationCode = State()


# /find - Поиск товара
@dp.message_handler(commands='find')
async def cmd_find(message: Message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(InlineKeyboardButton('По наименованию', callback_data='name'),
                 InlineKeyboardButton('По артикулу', callback_data='code'))
    keyboard.add(InlineKeyboardButton('По штрихкоду', callback_data='barcode'),
                 InlineKeyboardButton('По ISBN', callback_data='isbn'))
    await message.answer('Выберите способ поиска:', reply_markup=keyboard)


# /doc - Получить документ
@dp.message_handler(commands='doc')
async def cmd_doc(message: Message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(InlineKeyboardButton('УПД', callback_data='upd'),
                 InlineKeyboardButton('Счет на оплату', callback_data='invoice'))
    keyboard.add(InlineKeyboardButton('Реализация товаров', callback_data='sale'),
                 InlineKeyboardButton('Приходная накладная', callback_data='receipt'))
    await message.answer('Выберите вид документа:', reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data)
async def process_callback(callback_query: types.CallbackQuery):
    command = callback_query.data
    await bot.answer_callback_query(callback_query.id)
    if command == 'name':
        answer = 'Введите наименование товара'
    elif command == 'code':
        answer = 'Введите артикул товара'
    elif command == 'barcode':
        answer = 'Введите штрихкод товара'
    elif command == 'isbn':
        answer = 'Введите ISBN'
    elif command == 'upd' or command == 'invoice' or command == 'sale' or command == 'receipt':
        answer = 'Введите номер документа'
    else:
        return
    await bot.send_message(callback_query.from_user.id, answer)
    await set_variable(command)
    await UserInput.searchText.set()


@dp.message_handler(state=UserInput.searchText, content_types=ContentTypes.TEXT)
async def search_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    command = data['var']
    await state.finish()
    await send_request(message, command, data=message.text)


# /orders - Получение списка заказов
@dp.message_handler(commands='orders')
async def cmd_orders(message: Message):
    amount = message.get_args()
    await send_request(message, 'orders', data=int(amount) if amount and amount.isdecimal() else 50)


# /status - Получение статуса заказа
@dp.message_handler(commands='status')
async def cmd_status(message: Message):
    order_number = message.get_args()
    if not order_number or not order_number.isdecimal():
        await message.answer('Введите номер заказа')
        await UserInput.orderNumber.set()
    else:
        await send_request(message, 'status', data=order_number)


@dp.message_handler(state=UserInput.orderNumber, content_types=ContentTypes.TEXT)
async def order_number_input(message: Message, state: FSMContext):
    order_number = message.text
    await state.finish()
    if order_number.isdecimal():
        await send_request(message, 'status', data=order_number)
    else:
        await message.answer('Некорректный номер заказа')


# /register - Регистрация в 1С
@dp.message_handler(commands='register')
async def cmd_register(message: Message):
    user_email = message.get_args()
    if not user_email:
        await message.answer('Введите email')
        await UserInput.userEmail.set()
    else:
        await verification_request(message, user_email)


@dp.message_handler(state=UserInput.userEmail, content_types=ContentTypes.TEXT)
async def email_input(message: Message, state: FSMContext):
    await state.finish()
    await verification_request(message, message.text)


async def verification_request(message, user_email):
    params = await send_request(message, 'register', email=user_email)
    if not params:
        return
    await set_variable(params)
    await UserInput.verificationCode.set()


@dp.message_handler(state=UserInput.verificationCode, content_types=ContentTypes.TEXT)
async def verification_code_input(message: Message, state: FSMContext):
    data = await state.get_data()
    params = data['var']
    await state.finish()
    if params['code'] == message.text:
        await send_request(message, 'confirm', guid=params['guid'])
    else:
        await message.answer('Неверный код')


# /debts - Получение задолженностей
@dp.message_handler(commands='debts')
async def cmd_debts(message: Message):
    await send_request(message, 'debts')


# /promos - Вывести действующие акции
@dp.message_handler(commands='promos')
async def cmd_promos(message: Message):
    await send_request(message, 'promos')


# /price - Скачать прайс
@dp.message_handler(commands='price')
async def cmd_price(message: Message):
    await send_request(message, 'price')


# Все остальные обращения будут показывать справку
@dp.message_handler(content_types=ContentTypes.ANY)
async def echo_message(message: Message):
    help_text = 'Вы можете управлять мной, отправляя эти команды:' \
                '\n' \
                '\n/register - Зарегистрироваться в системе' \
                '\n/find - Найти товар' \
                '\n/orders - Показать список заказов' \
                '\n/status - Узнать статус заказа' \
                '\n/debts - Показать задолженности' \
                '\n/promos - Вывести действующие акции' \
                '\n/price - Скачать прайс' \
                '\n/doc - Получить документ'
    await message.answer(help_text)


async def send_request(message, command, **kwargs):
    await message.answer('Пожалуйста, подождите, я обрабатываю Ваш запрос...')
    params = None
    request = {'user': str(message.from_user.id), 'command': command}
    for key, value in kwargs.items():
        request[key] = value
    async with aiohttp.ClientSession(auth=auth) as session:
        # noinspection PyBroadException
        try:
            async with session.get(config.URL, json=request) as response:
                data = await response.json()
                if data:
                    # Получаем параметры
                    params = data.setdefault('params')
                    # Выводим сообщение
                    msg = data.setdefault('message')
                    if msg:
                        await message.answer(msg)
                    # Если есть массив сообщений, то выводим и их
                    msgs = data.setdefault('messages')
                    if msgs:
                        for msg in msgs:
                            await message.answer(msg)
                    # Если есть документы, то загружаем их
                    docs = data.setdefault('docs')
                    if docs:
                        for doc in docs:
                            filename = doc.get('name')
                            base64_string = base64.b64decode(doc.get('data'))
                            file = open(filename, 'wb')
                            file.write(base64_string)
                            file.close()
                            file = open(filename, 'rb')
                            await message.answer_document(file, caption=doc.get('caption'))
                            os.remove(filename)
                    # Если есть картинки, то показываем их
                    pics = data.setdefault('pics')
                    if pics:
                        for pic in pics:
                            filename = pic.get('name')
                            base64_string = base64.b64decode(pic.get('data'))
                            file = open(filename, 'wb')
                            file.write(base64_string)
                            file.close()
                            file = open(filename, 'rb')
                            await message.answer_photo(file, caption=pic.get('caption'))
                            os.remove(filename)
        except Exception:
            await message.answer('Упс... Что-то пошло не так')
        finally:
            await session.close()
    return params


async def set_variable(var):
    state = Dispatcher.get_current().current_state()
    await state.update_data(var=var)


async def on_startup(dispatcher: Dispatcher):
    # Регистрация команд, отображаемых в интерфейсе бота
    commands = [
        BotCommand('/help', 'Показать список всех доступных команд'),
        BotCommand('/register', 'Зарегистрироваться'),
        BotCommand('/find', 'Найти товар'),
        BotCommand('/orders', 'Показать список заказов'),
        BotCommand('/status', 'Узнать статус заказа'),
        BotCommand('/debts', 'Показать задолженности'),
        BotCommand('/promos', 'Вывести действующие акции'),
        BotCommand('/price', 'Скачать прайс'),
        BotCommand('/doc', 'Получить документ'),
    ]
    await dispatcher.bot.set_my_commands(commands)


async def on_shutdown(dispatcher: Dispatcher):
    await dispatcher.storage.close()
    await dispatcher.storage.wait_closed()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)