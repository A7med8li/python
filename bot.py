import discord
from discord import app_commands
from discord.ext import commands
import requests
import os
import json
from dotenv import load_dotenv
import asyncio
import typing
from keep_alive import keep_alive

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if not DISCORD_BOT_TOKEN:
    print(
        "CRITICAL ERROR: Discord bot token (DISCORD_BOT_TOKEN) not found in .env file!"
    )
    exit()

# تكوين Pterodactyl الأساسي
PTERO_CONFIG = {
    'panel_url': os.getenv('PTERO_PANEL_URL'),
    'api_key': os.getenv('PTERO_API_KEY'),
    'server_id': os.getenv('PTERO_SERVER_ID')
}

# التحقق من التكوين الأساسي
if not all(PTERO_CONFIG.values()):
    print("CRITICAL ERROR: Missing Pterodactyl configuration in .env file!")
    exit()


def get_api_headers():
    return {
        'Authorization': f'Bearer {PTERO_CONFIG["api_key"]}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# متغيرات لتتبع حالة السيرفر
status_check_active = False
status_message = None
status_check_channel = None


async def send_ptero_power_command(command: str, friendly_name: str):
    api_url = f"{PTERO_CONFIG['panel_url']}/api/client/servers/{PTERO_CONFIG['server_id']}/power"
    payload = {'signal': command}

    try:
        response = requests.post(api_url,
                                 headers=get_api_headers(),
                                 json=payload,
                                 timeout=15)
        response.raise_for_status()
        return True, f"تم {friendly_name} السيرفر بنجاح"
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 409:
            return False, "السيرفر بالفعل في هذه الحالة"
        return False, f"خطأ في {friendly_name} السيرفر: {err.response.status_code}"
    except Exception as e:
        return False, f"خطأ غير متوقع: {str(e)}"


async def get_server_status():
    api_url = f"{PTERO_CONFIG['panel_url']}/api/client/servers/{PTERO_CONFIG['server_id']}/resources"

    try:
        response = requests.get(api_url, headers=get_api_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()

        status = data.get('attributes', {}).get('current_state', 'unknown')
        resources = data.get('attributes', {}).get('resources', {})

        return True, {
            'status': status,
            'cpu': resources.get('cpu_absolute', 0),
            'memory': resources.get('memory_bytes', 0) / (1024**2),
            'disk': resources.get('disk_bytes', 0) / (1024**2)
        }
    except Exception as e:
        return False, f"فشل في جلب حالة السيرفر: {str(e)}"


async def join_queue():
    api_url = f"{PTERO_CONFIG['panel_url']}/api/client/servers/{PTERO_CONFIG['server_id']}/join-queue"

    try:
        response = requests.post(api_url,
                                 headers=get_api_headers(),
                                 timeout=15)
        response.raise_for_status()
        return True, "تم إضافة السيرفر إلى طابور الانتظار بنجاح"
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 422:
            return False, "queue_unavailable"  # رمز خاص يشير إلى أن الطابور غير متاح
        return False, f"خطأ في إضافة السيرفر إلى الطابور: {err.response.status_code}"
    except Exception as e:
        return False, f"خطأ غير متوقع: {str(e)}"


async def check_server_status(interaction: discord.Interaction):
    global status_check_active, status_message, status_check_channel

    status_check_active = True
    status_check_channel = interaction.channel

    while status_check_active:
        success, result = await get_server_status()

        if not success:
            embed = discord.Embed(title="حالة السيرفر",
                                  description=result,
                                  color=discord.Color.red())
            await status_message.edit(embed=embed)
            break

        status_emoji = {
            'running': '🟢',
            'offline': '🔴',
            'starting': '🟡',
            'stopping': '🟠'
        }.get(result['status'].lower(), '⚪')

        embed = discord.Embed(title="حالة السيرفر", color=discord.Color.blue())

        embed.add_field(
            name="الحالة",
            value=f"{status_emoji} {result['status'].capitalize()}",
            inline=False)

        embed.add_field(name="استهلاك الموارد",
                        value=f"**CPU:** {result['cpu']:.1f}%\n"
                        f"**الذاكرة:** {result['memory']:.1f} MB\n"
                        f"**التخزين:** {result['disk']:.1f} MB",
                        inline=False)

        try:
            await status_message.edit(embed=embed)
        except:
            pass

        # إذا كان السيرفر يعمل، نتوقف عن المتابعة
        if result['status'].lower() == 'running':
            status_check_active = False
            embed = discord.Embed(title="حالة السيرفر",
                                  description="🟢 السيرفر يعمل الآن بنجاح!",
                                  color=discord.Color.green())
            await status_message.edit(embed=embed)
            break

        await asyncio.sleep(5)  # التحقق كل 5 ثواني


@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user.name} (ID: {bot.user.id})')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")


# مجموعة أوامر Pterodactyl
ptero = app_commands.Group(name="server",
                           description="أوامر التحكم في سيرفر Pterodactyl")


@ptero.command(name="status", description="عرض حالة السيرفر واستهلاك الموارد")
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    success, result = await get_server_status()

    if not success:
        await interaction.followup.send(result)
        return

    embed = discord.Embed(title="حالة السيرفر", color=discord.Color.blue())

    status_emoji = {
        'running': '🟢',
        'offline': '🔴',
        'starting': '🟡',
        'stopping': '🟠'
    }.get(result['status'].lower(), '⚪')

    embed.add_field(name="الحالة",
                    value=f"{status_emoji} {result['status'].capitalize()}",
                    inline=False)

    embed.add_field(name="استهلاك الموارد",
                    value=f"**CPU:** {result['cpu']:.1f}%\n"
                    f"**الذاكرة:** {result['memory']:.1f} MB\n"
                    f"**التخزين:** {result['disk']:.1f} MB",
                    inline=False)

    await interaction.followup.send(embed=embed)


@ptero.command(name="start",
               description="تشغيل السيرفر مع محاولة إضافته إلى طابور الانتظار")
async def start(interaction: discord.Interaction):
    global status_message, status_check_active

    if status_check_active:
        await interaction.response.send_message(
            "يتم بالفعل متابعة حالة السيرفر", ephemeral=True)
        return

    await interaction.response.defer()

    # أولاً نحاول إضافة السيرفر إلى الطابور
    queue_success, queue_message = await join_queue()

    if queue_message == "queue_unavailable":
        # إذا كان الطابور غير متاح (خطأ 422)، نبدأ السيرفر مباشرة
        start_success, start_message = await send_ptero_power_command(
            "start", "تشغيل")

        if not start_success:
            await interaction.followup.send(start_message)
            return

        # بدء متابعة حالة السيرفر
        embed = discord.Embed(
            title="حالة السيرفر",
            description="🚀 جاري تشغيل السيرفر مباشرة (الطابور غير متاح)...",
            color=discord.Color.orange())
        status_message = await interaction.followup.send(embed=embed)

        # بدء المهمة الخلفية لمتابعة الحالة
        bot.loop.create_task(check_server_status(interaction))
    elif queue_success:
        # إذا تمت إضافة السيرفر إلى الطابور بنجاح
        embed = discord.Embed(
            title="حالة السيرفر",
            description=
            "⏳ تم إضافة السيرفر إلى طابور الانتظار، جاري التشغيل...",
            color=discord.Color.blue())
        status_message = await interaction.followup.send(embed=embed)

        # بدء المهمة الخلفية لمتابعة الحالة
        bot.loop.create_task(check_server_status(interaction))
    else:
        # إذا فشلت محاولة إضافة السيرفر إلى الطابور
        await interaction.followup.send(queue_message)


@ptero.command(name="stop", description="إيقاف السيرفر")
async def stop(interaction: discord.Interaction):
    global status_check_active

    status_check_active = False  # إيقاف أي متابعة لحالة السيرفر
    await interaction.response.defer()
    success, message = await send_ptero_power_command("stop", "إيقاف")
    await interaction.followup.send(message)


@ptero.command(name="restart", description="إعادة تشغيل السيرفر")
async def restart(interaction: discord.Interaction):
    global status_check_active

    status_check_active = False  # إيقاف أي متابعة لحالة السيرفر مؤقتًا
    await interaction.response.defer()
    success, message = await send_ptero_power_command("restart", "إعادة تشغيل")

    if success:
        # بدء متابعة حالة السيرفر بعد إعادة التشغيل
        embed = discord.Embed(title="حالة السيرفر",
                              description="🔄 جاري إعادة تشغيل السيرفر...",
                              color=discord.Color.orange())
        status_message = await interaction.followup.send(embed=embed)
        bot.loop.create_task(check_server_status(interaction))
    else:
        await interaction.followup.send(message)


@ptero.command(name="help", description="عرض جميع الأوامر المتاحة")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="أوامر البوت",
                          description="قائمة بأوامر التحكم في السيرفر",
                          color=discord.Color.green())

    embed.add_field(name="/server status",
                    value="عرض حالة السيرفر واستهلاك الموارد",
                    inline=False)

    embed.add_field(name="/server start",
                    value="تشغيل السيرفر مع محاولة إضافته إلى طابور الانتظار",
                    inline=False)

    embed.add_field(name="/server stop", value="إيقاف السيرفر", inline=False)

    embed.add_field(name="/server restart",
                    value="إعادة تشغيل السيرفر",
                    inline=False)

    await interaction.response.send_message(embed=embed)


# إضافة مجموعة الأوامر للبوت
bot.tree.add_command(ptero)
keep_alive()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send(f"حدث خطأ: {str(error)}")


if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
