import discord
from discord.ext import commands
from discord import app_commands
import requests
import os
from datetime import datetime
import asyncio
import logging
from flask import Flask
import threading

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
FACEIT_API_KEY = os.getenv('FACEIT_API_KEY')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
TARGET_PLAYER = "UNCRKING"
PORT = int(os.getenv('PORT', 10000))

# ========== ВЕБ-СЕРВЕР ДЛЯ UPTIMEROBOT ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "Faceit бот работает! 🤖"

@app.route('/ping')
def ping():
    logging.info("🏓 Получен пинг от UptimeRobot")
    return "pong", 200

def run_web_server():
    """Запускает веб-сервер в отдельном потоке"""
    app.run(host='0.0.0.0', port=PORT)

# ========== НАСТРОЙКИ БОТА ==========
intents = discord.Intents.default()
intents.message_content = True

class FaceitBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        logging.info(f"✅ Бот {self.user} запущен!")
        logging.info(f"📡 Отслеживаем игрока: {TARGET_PLAYER}")
        logging.info(f"📢 Канал для оповещений: {CHANNEL_ID}")
        logging.info(f"🌐 Веб-сервер запущен на порту {PORT}")
        # Запускаем фоновую задачу
        self.loop.create_task(self.check_match_loop())

    async def check_match_loop(self):
        """Фоновая задача для проверки матчей"""
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)
        
        if not channel:
            logging.error(f"❌ Канал с ID {CHANNEL_ID} не найден!")
            return
        
        last_match_id = None
        check_count = 0
        
        while not self.is_closed():
            try:
                check_count += 1
                logging.info(f"🔍 Проверка матча #{check_count}")
                
                match_info = await self.get_current_match_info(TARGET_PLAYER)
                
                if match_info and match_info['match_id'] != last_match_id:
                    last_match_id = match_info['match_id']
                    
                    embed = discord.Embed(
                        title=f"🎮 {TARGET_PLAYER} запустил матч!",
                        description=f"[Ссылка на комнату матча]({match_info['room_url']})",
                        color=0x00FF00,
                        timestamp=datetime.now()
                    )
                    
                    embed.add_field(name="🗺️ Карта", value=match_info['map'], inline=True)
                    embed.add_field(name="🌍 Сервер", value=match_info['server'], inline=True)
                    
                    team1_text = ""
                    team2_text = ""
                    
                    for i, player in enumerate(match_info['teams'][0], 1):
                        team1_text += f"{i}. **{player['nickname']}** - {player['elo']} ELO\n"
                    
                    for i, player in enumerate(match_info['teams'][1], 1):
                        team2_text += f"{i}. **{player['nickname']}** - {player['elo']} ELO\n"
                    
                    embed.add_field(name="👥 Команда 1", value=team1_text or "❌ Нет данных", inline=True)
                    embed.add_field(name="👥 Команда 2", value=team2_text or "❌ Нет данных", inline=True)
                    
                    await channel.send(embed=embed)
                    logging.info(f"✅ Оповещение о матче {match_info['match_id']} отправлено!")
                    
                    await asyncio.sleep(300)  # Ждем 5 минут перед следующей проверкой этого же матча
                
                # Ждем 2 минуты до следующей проверки
                await asyncio.sleep(120)
                
            except Exception as e:
                logging.error(f"❌ Ошибка в фоновой задаче: {e}")
                await asyncio.sleep(60)

    async def get_player_id(self, nickname):
        """Получает ID игрока по нику"""
        url = f"https://open.faceit.com/data/v4/players?nickname={nickname}"
        headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()['player_id']
            else:
                logging.error(f"❌ Ошибка получения ID: {response.status_code}")
                return None
        except Exception as e:
            logging.error(f"❌ Ошибка: {e}")
            return None

    async def get_current_match_info(self, nickname):
        """Получает информацию о текущем матче"""
        player_id = await self.get_player_id(nickname)
        if not player_id:
            return None
        
        headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
        
        try:
            url = f"https://open.faceit.com/data/v4/players/{player_id}/current-match"
            response = requests.get(url, headers=headers)
            
            if response.status_code != 200:
                return None
            
            match_data = response.json()
            
            if not match_data or 'match_id' not in match_data:
                return None
            
            match_id = match_data['match_id']
            match_url = f"https://open.faceit.com/data/v4/matches/{match_id}"
            match_response = requests.get(match_url, headers=headers)
            
            if match_response.status_code != 200:
                return None
            
            full_match = match_response.json()
            
            teams = []
            for team in full_match['teams']:
                team_players = []
                for player in team['roster']:
                    team_players.append({
                        'nickname': player['nickname'],
                        'elo': player.get('game_skill_level', '?')
                    })
                teams.append(team_players)
            
            map_name = full_match.get('voting', {}).get('map', {}).get('pick', ['Unknown'])[0]
            
            region_map = {
                'EU': 'Europe', 'NA': 'North America', 'SA': 'South America',
                'OCE': 'Oceania', 'ASIA': 'Asia'
            }
            server_region = full_match.get('region', 'EU')
            server = region_map.get(server_region, server_region)
            
            return {
                'match_id': match_id,
                'room_url': f"https://www.faceit.com/ru/cs2/room/{match_id}",
                'map': map_name,
                'server': server,
                'teams': teams
            }
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения матча: {e}")
            return None

    async def get_player_stats(self, nickname):
        """Получает статистику игрока"""
        player_id = await self.get_player_id(nickname)
        if not player_id:
            return None
        
        headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
        
        try:
            player_url = f"https://open.faceit.com/data/v4/players/{player_id}"
            player_response = requests.get(player_url, headers=headers)
            
            history_url = f"https://open.faceit.com/data/v4/players/{player_id}/history?game=cs2&offset=0&limit=30"
            history_response = requests.get(history_url, headers=headers)
            
            if player_response.status_code != 200 or history_response.status_code != 200:
                return None
            
            player_data = player_response.json()
            history_data = history_response.json()
            
            elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 0)
            level = player_data.get('games', {}).get('cs2', {}).get('skill_level', 0)
            
            matches = history_data.get('items', [])
            
            if not matches:
                return {
                    'elo': elo, 'level': level, 'winrate': 0, 
                    'kd': 0.0, 'matches_today': 0, 'total_matches': 0
                }
            
            wins = 0
            total_kills = 0
            total_deaths = 0
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            matches_today = 0
            
            for match in matches:
                for team in match['teams']:
                    for player in team['players']:
                        if player['nickname'].lower() == nickname.lower():
                            if team.get('victory') is True:
                                wins += 1
                            
                            player_stats = player.get('player_stats', {})
                            total_kills += int(player_stats.get('Kills', 0))
                            total_deaths += int(player_stats.get('Deaths', 0))
                            
                            match_date = datetime.fromtimestamp(match['created_at'] / 1000)
                            if match_date >= today_start:
                                matches_today += 1
                            break
            
            total_matches = len(matches)
            winrate = round((wins / total_matches * 100), 1) if total_matches > 0 else 0
            kd = round(total_kills / total_deaths, 2) if total_deaths > 0 else 0.0
            
            return {
                'elo': elo, 'level': level, 'winrate': winrate,
                'kd': kd, 'matches_today': matches_today,
                'total_matches': total_matches
            }
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения статистики: {e}")
            return None

# ========== СОЗДАЕМ ЭКЗЕМПЛЯР БОТА ==========
bot = FaceitBot()

# ========== КОМАНДЫ ==========
@bot.tree.command(name="stats", description="Показать статистику игрока UNCRKING")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer()
    
    stats_data = await bot.get_player_stats(TARGET_PLAYER)
    
    if not stats_data:
        await interaction.followup.send("❌ Не удалось получить статистику игрока")
        return
    
    embed = discord.Embed(
        title=f"📊 Статистика {TARGET_PLAYER}",
        color=0xFF5500,
        timestamp=datetime.now()
    )
    
    embed.add_field(name="🎮 Уровень", value=f"**{stats_data['level']}**", inline=True)
    embed.add_field(name="⭐ ELO", value=f"**{stats_data['elo']}**", inline=True)
    embed.add_field(name="📈 Винрейт (30 матчей)", value=f"**{stats_data['winrate']}%**", inline=True)
    embed.add_field(name="⚔️ K/D (30 матчей)", value=f"**{stats_data['kd']}**", inline=True)
    embed.add_field(name="📅 Игр сегодня", value=f"**{stats_data['matches_today']}**", inline=True)
    embed.add_field(name="🎯 Всего матчей", value=f"**{stats_data['total_matches']}**", inline=True)
    
    embed.add_field(
        name="🔗 Ссылки",
        value=f"[Профиль Faceit](https://www.faceit.com/ru/players/{TARGET_PLAYER})",
        inline=False
    )
    
    embed.set_footer(text="Данные обновлены")
    
    await interaction.followup.send(embed=embed)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    logging.info("🚀 Запуск Faceit бота с веб-сервером...")
    
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Запускаем Discord бота
    bot.run(DISCORD_TOKEN)
