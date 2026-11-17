# 🚖 Campus Shuttle Telegram Bot

A Telegram bot designed for university students to quickly book and navigate shuttle rides between their halls of residence and key academic / campus destinations (Class, CUCRID, Caf 2, Civil, CST, CMSS, EIE, Mech) and back.

The bot's menu and interactive experience are structured like the reference UI (custom reply keyboard buttons + clean inline step-by-step pickers).

---

## 🌟 Key Features

1. **Two-Way Trips**:
   - **Outward (`🚖 Book a Shuttle`)**: Hall $\rightarrow$ Campus location (Class, CUCRID, Caf 2, CST, CMSS, Civil, EIE, Mech).
   - **Return (`🔄 Return Trip`)**: Campus location $\rightarrow$ Student Hall.
2. **Interactive UI**:
   - Persistent 2x2 multi-option grid menu matching the reference design.
   - Clean inline keyboards for selecting Halls, Destinations, and Passenger count.
   - Ride summary preview with fare calculations before confirmation.
3. **Active Rides & Management**:
   - Real-time status tracker (`📋 Active Rides / Status`).
   - One-tap cancellation or marking rides as completed.
4. **Student Profiles**:
   - `👤 My Profile` tracks ride history and allows setting preferred halls or contact phone numbers.

---

## 📁 Project Structure

```
.
├── bot.py           # Main bot logic, handlers, and FSM states
├── keyboards.py     # Menu layouts & inline keyboard generators
├── storage.py       # User profiles & ride request persistence (JSON-backed)
├── config.py        # Location definitions, fares, and environment variables
├── requirements.txt # Python dependencies (aiogram 3.x, python-dotenv)
├── .env.example     # Template for Telegram token configuration
└── .env             # Bot token configuration file
```

---

## 🚀 Setup & Running

### 1. Obtain a Bot Token
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the instructions to choose a name and username.
3. Copy the HTTP API token provided.

### 2. Configure Token
Add your token to [.env](file:///home/eddy/Documents/Projects/Shuttles%20Bot/.env):
```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
```

### 3. Run the Bot
The virtual environment has already been installed with `aiogram 3.x`. Run:
```bash
./venv/bin/python3 bot.py
```
*(Or activate your virtual environment with `source venv/bin/activate` and run `python3 bot.py`)*

---

## 📍 Covered Locations
- **Halls:** Peter, Paul, John, Joseph, Daniel, Esther, Mary, Lydia, Dorcas, Deborah
- **Campus Hubs:** Class / Lecture Theatres, CUCRID, Caf 2, Civil Building, CST Building, CMSS Building, EIE Building, Mech Building
