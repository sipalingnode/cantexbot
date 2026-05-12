<p align="center">
  <img height="300" height="auto" src="https://github.com/sipalingnode/sipalingnode/blob/main/logo.png">
</p>

<h2 align="center"><b>Follow Community Team</b></h2>
<p align="center">
  <a href="https://www.airdropasc.com" target="_blank"><img src="https://github.com/sipalingnode/sipalingnode/blob/main/logo.png" width="50"/></a>&nbsp;&nbsp;&nbsp;
  <a href="https://t.me/airdropasc" target="_blank"><img src="https://github.com/user-attachments/assets/56e7f6ee-18b7-4b36-becc-ec6e4de7bff9" width="50"/></a>&nbsp;&nbsp;&nbsp;
  <a href="https://x.com/Autosultan_team" target="_blank"><img src="https://github.com/user-attachments/assets/fbb43aa4-9652-4a49-b984-5cf032b6b1ac" width="50"/></a>&nbsp;&nbsp;&nbsp;
  <a href="https://www.youtube.com/@ZamzaSalim" target="_blank"><img src="https://github.com/user-attachments/assets/c15509f9-acb7-49ce-989a-5bac62e7e549" width="50"/></a>
</p>

---

# CANTEX BOT EARN UP TO 25 CC/DAY [SOURCE](https://t.me/airdropasc/89245)

# Features

- Multi Account
- Telegram Control & Monitoring
- Auto Swap CC ↔ USDCX
- Snapshot Target
- Gas Fee Tracking
- Weekly Gas Fee Report

### Install dependency

```
sudo apt install python3 python3-pip git -y
```

---

### Clone repository

```
git clone https://github.com/sipalingnode/cantexbot.git
cd cantexbot
```

---

### Buat virtual environment

```
python3 -m venv venv
source venv/bin/activate
```

---

### Install python package

```
pip install aiohttp python-telegram-bot==20.7
```

---

### Clone SDK

```
git clone https://github.com/caviarnine/cantex_sdk.git
cd cantex_sdk
pip install -e .
```

---

### Kembali ke folder bot

```
cd ~/cantexbot
```

---

# Setup Telegram
### Create Telegram Bot
* Open [BotFather](https://t.me/BotFather)
* Send: `/newbot`
* Enter bot name & username
* Copy the BOT TOKEN
### Get Telegram Chat ID
* Open [GetID](https://t.me/userinfobot)
* Send: /start
* Copy your Chat ID
### Paste Bot Token & Chat ID di config.json

```
nano config.json
```
**Save file config.json dengan `CTRL+X+Y lalu Enter`**

---

# Run Bot

```
python3 bot.py
```

Jika berhasil:

```
[INFO] CANTEXBOT READY ON TELEGRAM
```

Dan Telegram akan mengirim:

```
[INFO] SEND /startbot TO SEE MENU
```

---

# Telegram Command

## Start Menu

```
/startbot
```

---

## Add Account

Jika `/autoswap` sedang berjalan:

```
/stopbot
```

Tambah account:

```
/addaccount
```

Bot akan meminta:
1. Nama account
2. Operator key
3. Trading key

Contoh:

```
acc01
```

```
operator_key
```

```
trading_key
```

Bot otomatis menyimpan ke `accounts.json`.

---

## Set Max Gas Fee

```
/setgwei 0.35
```

---

## Set Snapshot Target

```
/snapshot 50
```

Artinya:
- stop setelah 50 success swap per account.

---

## Set Delay

```
/setdelay 300 360
```

Artinya:
- delay random 300-360 detik.

---

## Start Autoswap

```
/autoswap
```

Bot akan:
- swap otomatis
- stop saat target tercapai
- lanjut otomatis setiap hari jam 10 WIB.

---

## Stop Bot

```
/stopbot
```

---

## Bot Status

```
/status
```

---

## Check Balance

```
/balance
```

---

## Check Address

```
/address
```

---

## Check Gas Fee

```
/gasfee
```

---

## Weekly Gas Fee

```
/weeklygas
```

---

## Reset Gas Fee

```
/resetgasfee
```

---

# Notes

- Minimal balance agar bot tetap berjalan:
  - `> 12 CC`

- Jika:
  - CC <= 12
  - dan USDCX kosong

maka account otomatis stop.

- Untuk menambahkan account baru saat autoswap:
  1. `/stopbot`
  2. `/addaccount`
  3. `/autoswap`
