import config
import logging
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import BotCommand, ContentTypes, ParseMode
from aiogram.utils import executor

# Настроим логирование
logging.basicConfig(level=logging.INFO)

# Инициализируем бота
bot = Bot(token=config.TOKEN)
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
async def cmd_find(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(types.InlineKeyboardButton('По наименованию', callback_data='name'),
                 types.InlineKeyboardButton('По артикулу', callback_data='code'))
    keyboard.add(types.InlineKeyboardButton('По штрихкоду', callback_data='barcode'),
                 types.InlineKeyboardButton('По ISBN', callback_data='isbn'))
    await message.answer('Выберите способ поиска:', reply_markup=keyboard)


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
    else:
        return
    await bot.send_message(callback_query.from_user.id, answer)
    await set_variable(command)
    await UserInput.searchText.set()


@dp.message_handler(state=UserInput.searchText, content_types=types.ContentTypes.TEXT)
async def search_text_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    command = data['var']
    await state.finish()
    await send_request(message, command, data=message.text)


# /orders - Получение списка заказов
@dp.message_handler(commands='orders')
async def cmd_orders(message: types.Message):
    amount = message.get_args()
    await send_request(message, 'orders', data=amount if amount and amount.isdecimal() else [])


# /status - Получение статуса заказа
@dp.message_handler(commands='status')
async def cmd_status(message: types.Message):
    order_number = message.get_args()
    if not order_number or not order_number.isdecimal():
        await message.answer('Введите номер заказа')
        await UserInput.orderNumber.set()
    else:
        await send_request(message, 'status', data=order_number)


@dp.message_handler(state=UserInput.orderNumber, content_types=types.ContentTypes.TEXT)
async def order_number_input(message: types.Message, state: FSMContext):
    order_number = message.text
    await state.finish()
    if order_number.isdecimal():
        await send_request(message, 'status', data=order_number)
    else:
        await message.answer('Некорректный номер заказа')


# /register - Регистрация в 1С
@dp.message_handler(commands='register')
async def cmd_register(message: types.Message):
    user_email = message.get_args()
    if not user_email:
        await message.answer('Введите email')
        await UserInput.userEmail.set()
    else:
        await verification_request(message, user_email)


@dp.message_handler(state=UserInput.userEmail, content_types=types.ContentTypes.TEXT)
async def email_input(message: types.Message, state: FSMContext):
    await state.finish()
    await verification_request(message, message.text)


async def verification_request(message, user_email):
    params = await send_request(message, 'register', email=user_email)
    if not params:
        return
    await set_variable(params)
    await UserInput.verificationCode.set()


@dp.message_handler(state=UserInput.verificationCode, content_types=types.ContentTypes.TEXT)
async def verification_code_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    params = data['var']
    await state.finish()
    if params['code'] == message.text:
        await send_request(message, 'confirm', guid=params['guid'])
    else:
        await message.answer('Неверный код')


# /debts - Получение задолженностей
@dp.message_handler(commands='debts')
async def cmd_debts(message: types.Message):
    await send_request(message, 'debts')


# Все остальные обращения будут показывать справку
@dp.message_handler(content_types=ContentTypes.ANY)
async def echo_message(message: types.Message):
    help_text = 'Вы можете управлять мной, отправляя эти команды:' \
                '\n' \
                '\n/register - Зарегистрироваться в системе' \
                '\n/find - Найти товар' \
                '\n/orders - Показать список заказов' \
                '\n/status - Узнать статус заказа' \
                '\n/debts - Показать задолженности'
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


async def send_request(message, command, **kwargs):
    await message.answer('Пожалуйста, подождите, я обрабатываю Ваш запрос...')
    params = None
    request = {'user': str(message.from_user.id), 'command': command}
    for key, value in kwargs.items():
        request[key] = value
    async with aiohttp.ClientSession(auth=auth) as session:
        try:
            async with session.get(config.URL, json=request) as response:
                data = await response.json()
                if data:
                    # Выводим сообщение
                    msg = data.setdefault('message')
                    if msg:
                        await message.answer(msg, parse_mode=ParseMode.MARKDOWN)
                    # Получаем параметры
                    params = data.setdefault('params')
                    if params:
                        # Если в параметрах есть свои сообщения то выводим и их
                        msgs = params.setdefault('messages')
                        if msgs:
                            for msg in msgs:
                                await message.answer(msg, parse_mode=ParseMode.MARKDOWN)
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
    ]
    await dispatcher.bot.set_my_commands(commands)


async def on_shutdown(dispatcher: Dispatcher):
    await dispatcher.storage.close()
    await dispatcher.storage.wait_closed()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
