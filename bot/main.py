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


class DataInput(StatesGroup):
    textInput = State()
    numInput = State()


@dp.message_handler(commands='find')
async def cmd_find(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(types.InlineKeyboardButton('По наименованию', callback_data='name'),
                 types.InlineKeyboardButton('По артикулу', callback_data='code'))
    keyboard.add(types.InlineKeyboardButton('По штрихкоду', callback_data='barcode'),
                 types.InlineKeyboardButton('По ISBN', callback_data='isbn'))
    await message.answer("Выберите способ поиска:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data)
async def process_callback(callback_query: types.CallbackQuery):
    method = callback_query.data
    await bot.answer_callback_query(callback_query.id)
    if method == 'name':
        answer = 'Введите наименование товара'
    elif method == 'code':
        answer = 'Введите артикул товара'
    elif method == 'barcode':
        answer = 'Введите штрихкод товара'
    elif method == 'isbn':
        answer = 'Введите ISBN'
    else:
        return
    await bot.send_message(callback_query.from_user.id, answer)
    await set_method(method)
    await DataInput.textInput.set()


@dp.message_handler(commands='status')
async def cmd_status(message: types.Message):
    await set_method('status')
    arg = message.get_args()
    if not arg or not arg.isdecimal():
        await message.answer('Введите номер заказа')
        await DataInput.numInput.set()
    else:
        await show_response(message, arg)


@dp.message_handler(state=DataInput.textInput, content_types=types.ContentTypes.TEXT)
async def process_user_input(message: types.Message, state: FSMContext):
    arg = message.text
    await show_response(message, arg)


@dp.message_handler(state=DataInput.numInput, content_types=types.ContentTypes.TEXT)
async def process_user_input(message: types.Message, state: FSMContext):
    arg = message.text
    if not arg.isdecimal():
        await message.answer('Пожалуйста укажите корректный номер заказа')
        return
    await show_response(message, arg)


@dp.message_handler(content_types=ContentTypes.ANY)
async def echo_message(message: types.Message):
    help_text = 'Вы можете управлять мной, отправляя эти команды:' \
                '\n' \
                '\n/find - Уточнить цены и остатки товаров' \
                '\n/status - Узнать статус заказа'
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


async def show_response(message, arg):
    state = Dispatcher.get_current().current_state()
    user_data = await state.get_data()
    method = user_data['method']
    await state.finish()

    await message.answer('Пожалуйста, подождите, я обрабатываю Ваш запрос...')
    async with aiohttp.ClientSession(auth=auth) as session:
        try:
            async with session.get(config.URL + '/' + method + '/' + arg) as response:
                if response.status == 200:
                    msg = await response.text()
                    await message.answer(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
                else:
                    await message.answer('Извините, в настоящее время сервис недоступен (error ' + str(response.status) + ')')
        except Exception:
            await message.answer('Упс... Что-то пошло не так')
        finally:
            await session.close()


async def on_startup(dispatcher: Dispatcher):
    # Регистрация команд, отображаемых в интерфейсе бота
    commands = [
        BotCommand('/help', 'Показать список всех доступных команд'),
        BotCommand('/find', 'Уточнить цены и остатки товаров'),
        BotCommand('/status', 'Узнать статус заказа'),
    ]
    await dispatcher.bot.set_my_commands(commands)


async def on_shutdown(dispatcher: Dispatcher):
    await dispatcher.storage.close()
    await dispatcher.storage.wait_closed()


async def set_method(method):
    state = Dispatcher.get_current().current_state()
    await state.update_data(method=method)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
